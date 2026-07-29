"""
Arabic guide / help text for the VortexVPN CLI.

Used by: vortexvpn guide
"""
from __future__ import annotations

GUIDE_TEXT = """
╔══════════════════════════════════════════════════════════════════╗
║              دليل أوامر VortexVPN الكامل                          ║
╚══════════════════════════════════════════════════════════════════╝

═══════════════════════════════════════════════════════════════════
🚀 أوامر التشغيل الأساسية
═══════════════════════════════════════════════════════════════════

  vortexvpn run                          تشغيل السيرفر (نفس start)
  vortexvpn start                        تشغيل السيرفر في الخلفية
  vortexvpn start --password=MyPass123   تشغيل بكلمة سر خاصة
  vortexvpn stop                         إيقاف السيرفر
  vortexvpn restart                      إعادة تشغيل السيرفر
  vortexvpn status                       عرض حالة السيرفر
  vortexvpn logs                         عرض السجلات المباشرة

═══════════════════════════════════════════════════════════════════
🔗 ربط السيرفر بـ Domain حقيقي (HTTPS)
═══════════════════════════════════════════════════════════════════

  vortexvpn link https://server.vortevpn.org
      ↳ يضبط public_url على الدومين ويعيد التشغيل
      ↳ يحتاج Caddy/nginx مُفعّل على الدومين (شهادة HTTPS تلقائية)

  vortexvpn link https://server.vortevpn.org --admin-path=/x7k2m-secret
      ↳ يضبط الدومين + يغيّر مسار دخول المشرف لمسار مخفي

  مثال كامل:
    1. وجّه DNS A record من server.vortevpn.org إلى IP سيرفرك
    2. ثبّت Caddy: sudo apt install caddy
    3. انسخ Caddyfile: sudo cp docker/Caddyfile /etc/caddy/Caddyfile
    4. شغّل: vortexvpn link https://server.vortevpn.org
    5. النتيجة: https://server.vortevpn.org يعمل بـ HTTPS تلقائي

═══════════════════════════════════════════════════════════════════
⚙️  إعدادات السيرفر + إعادة تشغيل
═══════════════════════════════════════════════════════════════════

  vortexvpn settings
      ↳ يفتح محرر إعدادات تفاعلي
      ↳ يعرض الإعدادات الحالية ويسمح بتعديلها
      ↳ بعد التعديل، يطلب إعادة التشغيل تلقائياً

  vortexvpn settings --show
      ↳ عرض الإعدادات الحالية بلا تعديل

  vortexvpn settings --edit
      ↳ فتح configs/config.toml في $EDITOR مباشرة

  الإعدادات القابلة للتعديل:
    • web.port           — منفذ الواجهة (افتراضي 8080)
    • web.public_url     — الرابط العام (مثل https://server.vortevpn.org)
    • web.admin_path     — مسار دخول المشرف المخفي
    • tunnel.listen_port — منفذ النفق UDP (افتراضي 4433)
    • tunnel.max_clients — أقصى عدد عملاء (افتراضي 256)
    • tunnel.mtu         — حجم الحزمة (افتراضي 1400)
    • tunnel.cipher      — التشفير (aes-256-gcm)
    • log_level          — مستوى السجلات (INFO/DEBUG/WARNING)

═══════════════════════════════════════════════════════════════════
🔑 إدارة كلمات السر
═══════════════════════════════════════════════════════════════════

  vortexvpn show-password                عرض كلمة سر admin الحالية
  vortexvpn reset-password               تغيير كلمة سر admin (تفاعلي)
  vortexvpn reset-password --new=Pass123 تغيير كلمة سر بأمر واحد
  vortexvpn reset-password -u username   تغيير كلمة سر مستخدم معين

═══════════════════════════════════════════════════════════════════
👥 إدارة المستخدمين
═══════════════════════════════════════════════════════════════════

  vortexvpn add-user                     إضافة مستخدم جديد (تفاعلي)
  vortexvpn list-users                   عرض كل المستخدمين
  vortexvpn admin                        فتح Terminal إداري تفاعلي

═══════════════════════════════════════════════════════════════════
📱 معلومات الاتصال
═══════════════════════════════════════════════════════════════════

  vortexvpn connect                      عرض URL + admin + ports
                                          (يستعمل public_url إن وجد)

═══════════════════════════════════════════════════════════════════
🛠  Terminal الإداري التفاعلي (REPL)
═══════════════════════════════════════════════════════════════════

  vortexvpn admin
      ↳ يفتح shell تفاعلي بـ 13 أمر:
        help, status, stats, users, sessions,
        add-user, del-user, reset-password, toggle,
        kick, kick-all, version, exit

═══════════════════════════════════════════════════════════════════
📚 أمثلة شاملة
═══════════════════════════════════════════════════════════════════

  # أول تشغيل: كلمة سر خاصة
  vortexvpn run --password=MyStrongPass123

  # ربط بالدومين الحقيقي
  vortexvpn link https://server.vortevpn.org

  # عرض معلومات الاتصال
  vortexvpn connect

  # فتح Terminal الإدارة
  vortexvpn admin

  # تغيير الإعدادات
  vortexvpn settings

  # إعادة التشغيل بعد التعديل
  vortexvpn restart

═══════════════════════════════════════════════════════════════════
"""


def print_guide() -> None:
    """Print the full guide to stdout."""
    print(GUIDE_TEXT)
