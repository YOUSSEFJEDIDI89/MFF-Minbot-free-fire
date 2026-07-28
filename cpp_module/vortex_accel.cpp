// vortex_accel.cpp - C++ crypto acceleration for VortexVPN
//
// Provides AES-256-GCM (via OpenSSL EVP) bound to Python through pybind11.
// This is a hot-path optimisation: when the module is importable,
// CryptoEngine.seal/open use it; otherwise they fall back to the
// pure-Python cryptography library.
//
// Build:
//   make            # produces vortex_accel.cpython-<abi>-linux-x86_64.so
// Test:
//   python -c "import vortex_accel, os; \
//     k=os.urandom(32); n=os.urandom(12); \
//     ct=vortex_accel.aes_gcm_encrypt(k,n,b'hello',b''); \
//     print(vortex_accel.aes_gcm_decrypt(k,n,ct,b''))"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <stdexcept>
#include <vector>
#include <string>
#include <cstdint>

namespace py = pybind11;

// ---------------------------------------------------------------------
// AES-256-GCM
// ---------------------------------------------------------------------
static void openssl_check(int ok, const char* where) {
    if (!ok) throw std::runtime_error(std::string("OpenSSL error at ") + where);
}

// Encrypt: returns ciphertext||tag (tag appended, 16 bytes).
// Matches Python `cryptography.hazmat.primitives.ciphers.aead.AESGCM.encrypt`
// which returns ciphertext||tag in a single buffer.
static py::bytes aes_gcm_encrypt(
    const py::bytes& key_py,
    const py::bytes& nonce_py,
    const py::bytes& plaintext_py,
    const py::bytes& aad_py)
{
    std::string key = key_py;
    std::string nonce = nonce_py;
    std::string plaintext = plaintext_py;
    std::string aad = aad_py;

    if (key.size() != 32)  throw std::runtime_error("AES-256-GCM requires 32-byte key");
    if (nonce.size() != 12) throw std::runtime_error("GCM nonce must be 12 bytes");

    EVP_CIPHER_CTX* ctx = EVP_CIPHER_CTX_new();
    if (!ctx) throw std::runtime_error("EVP_CIPHER_CTX_new failed");

    std::vector<uint8_t> out(plaintext.size() + 16);  // ct + tag
    int len = 0;
    int out_len = 0;
    try {
        openssl_check(
            EVP_EncryptInit_ex(ctx, EVP_aes_256_gcm(), nullptr,
                               reinterpret_cast<const unsigned char*>(key.data()),
                               reinterpret_cast<const unsigned char*>(nonce.data())) == 1,
            "EVP_EncryptInit_ex");

        if (!aad.empty()) {
            openssl_check(
                EVP_EncryptUpdate(ctx, nullptr, &len,
                                  reinterpret_cast<const unsigned char*>(aad.data()),
                                  static_cast<int>(aad.size())) == 1,
                "EVP_EncryptUpdate (aad)");
        }

        openssl_check(
            EVP_EncryptUpdate(ctx, out.data(), &len,
                              reinterpret_cast<const unsigned char*>(plaintext.data()),
                              static_cast<int>(plaintext.size())) == 1,
            "EVP_EncryptUpdate (pt)");
        out_len = len;

        openssl_check(
            EVP_EncryptFinal_ex(ctx, out.data() + out_len, &len) == 1,
            "EVP_EncryptFinal_ex");
        out_len += len;

        openssl_check(
            EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG, 16,
                                out.data() + out_len) == 1,
            "EVP_CIPHER_CTX_ctrl GET_TAG");
        out_len += 16;
    } catch (...) {
        EVP_CIPHER_CTX_free(ctx);
        throw;
    }
    EVP_CIPHER_CTX_free(ctx);
    return py::bytes(reinterpret_cast<const char*>(out.data()), out_len);
}

// Decrypt: input is ciphertext||tag (16 trailing bytes).
static py::bytes aes_gcm_decrypt(
    const py::bytes& key_py,
    const py::bytes& nonce_py,
    const py::bytes& ct_py,
    const py::bytes& aad_py)
{
    std::string key = key_py;
    std::string nonce = nonce_py;
    std::string ct = ct_py;
    std::string aad = aad_py;

    if (key.size() != 32)    throw std::runtime_error("AES-256-GCM requires 32-byte key");
    if (nonce.size() != 12)  throw std::runtime_error("GCM nonce must be 12 bytes");
    if (ct.size() < 16)      throw std::runtime_error("ciphertext too short (no tag)");

    EVP_CIPHER_CTX* ctx = EVP_CIPHER_CTX_new();
    if (!ctx) throw std::runtime_error("EVP_CIPHER_CTX_new failed");

    size_t body_len = ct.size() - 16;
    std::vector<uint8_t> out(body_len);
    int len = 0, out_len = 0;
    try {
        openssl_check(
            EVP_DecryptInit_ex(ctx, EVP_aes_256_gcm(), nullptr,
                               reinterpret_cast<const unsigned char*>(key.data()),
                               reinterpret_cast<const unsigned char*>(nonce.data())) == 1,
            "EVP_DecryptInit_ex");

        if (!aad.empty()) {
            openssl_check(
                EVP_DecryptUpdate(ctx, nullptr, &len,
                                  reinterpret_cast<const unsigned char*>(aad.data()),
                                  static_cast<int>(aad.size())) == 1,
                "EVP_DecryptUpdate (aad)");
        }

        openssl_check(
            EVP_DecryptUpdate(ctx, out.data(), &len,
                              reinterpret_cast<const unsigned char*>(ct.data()),
                              static_cast<int>(body_len)) == 1,
            "EVP_DecryptUpdate (ct)");
        out_len = len;

        openssl_check(
            EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG, 16,
                const_cast<void*>(static_cast<const void*>(ct.data() + body_len))) == 1,
            "EVP_CIPHER_CTX_ctrl SET_TAG");

        int ok = EVP_DecryptFinal_ex(ctx, out.data() + out_len, &len);
        EVP_CIPHER_CTX_free(ctx);
        if (ok != 1) throw std::runtime_error("authentication failed");
        out_len += len;
        out.resize(out_len);
    } catch (...) {
        EVP_CIPHER_CTX_free(ctx);
        throw;
    }
    return py::bytes(reinterpret_cast<const char*>(out.data()), out.size());
}

// SHA-256 (used by the auth module as a fallback path).
static py::bytes sha256(const py::bytes& input_py) {
    std::string input = input_py;
    std::vector<uint8_t> out(32);
    EVP_MD_CTX* ctx = EVP_MD_CTX_new();
    if (!ctx) throw std::runtime_error("EVP_MD_CTX_new failed");
    EVP_DigestInit_ex(ctx, EVP_sha256(), nullptr);
    EVP_DigestUpdate(ctx, input.data(), input.size());
    unsigned int len = 32;
    EVP_DigestFinal_ex(ctx, out.data(), &len);
    EVP_MD_CTX_free(ctx);
    return py::bytes(reinterpret_cast<const char*>(out.data()), 32);
}

// Module
PYBIND11_MODULE(vortex_accel, m) {
    m.doc() = "VortexVPN C++ crypto accelerator (AES-256-GCM, SHA-256)";
    m.def("aes_gcm_encrypt", &aes_gcm_encrypt,
          py::arg("key"), py::arg("nonce"), py::arg("plaintext"), py::arg("aad") = py::bytes(""),
          "Encrypt with AES-256-GCM; returns ciphertext||tag.");
    m.def("aes_gcm_decrypt", &aes_gcm_decrypt,
          py::arg("key"), py::arg("nonce"), py::arg("ciphertext"), py::arg("aad") = py::bytes(""),
          "Decrypt + verify AES-256-GCM; input is ciphertext||tag.");
    m.def("sha256", &sha256, py::arg("input"), "SHA-256 of input bytes.");
    m.attr("version") = "1.0.0";
}
