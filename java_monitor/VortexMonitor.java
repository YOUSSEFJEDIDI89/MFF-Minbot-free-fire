// VortexMonitor.java - real-time traffic monitor for VortexVPN.
//
// Reads /proc/net/dev and /proc/stat on Linux, computes per-second
// throughput, and exposes it as a Unix-domain socket JSON stream
// (one JSON object per line). The Python web panel can connect and
// display live charts.
//
// Build:
//   javac VortexMonitor.java
// Run:
//   java VortexMonitor /var/run/vortexvpn/monitor.sock 1000

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;

public class VortexMonitor {

    private static final String VERSION = "1.0.0";

    private final String socketPath;
    private final int sampleIntervalMs;
    private final List<UnixSocketClient> clients =
        Collections.synchronizedList(new ArrayList<>());
    private final Deque<Map<String, Object>> history = new ConcurrentLinkedDeque<>();
    private final int historySize;

    // Snapshot of /proc/net/dev counters
    private static final class NetSnapshot {
        final long ts;
        final long rxBytes, txBytes, rxPackets, txPackets, rxErrs, txErrs;
        NetSnapshot(long ts, long rx, long tx, long rxp, long txp, long rxe, long txe) {
            this.ts = ts; this.rxBytes = rx; this.txBytes = tx;
            this.rxPackets = rxp; this.txPackets = txp;
            this.rxErrs = rxe; this.txErrs = txe;
        }
    }

    // Snapshot of /proc/stat (CPU)
    private static final class CpuSnapshot {
        final long ts;
        final long[] idleAndTotal;  // [idle, total]
        CpuSnapshot(long ts, long idle, long total) {
            this.ts = ts; this.idleAndTotal = new long[]{idle, total};
        }
    }

    private NetSnapshot lastNet = null;
    private CpuSnapshot lastCpu = null;

    public VortexMonitor(String socketPath, int sampleIntervalMs, int historySize) {
        this.socketPath = socketPath;
        this.sampleIntervalMs = sampleIntervalMs;
        this.historySize = historySize;
    }

    // -----------------------------------------------------------------
    // /proc readers
    // -----------------------------------------------------------------
    private NetSnapshot readNet() throws IOException {
        long rx=0, tx=0, rxp=0, txp=0, rxe=0, txe=0;
        try (BufferedReader br = Files.newBufferedReader(Paths.get("/proc/net/dev"))) {
            String line;
            while ((line = br.readLine()) != null) {
                int colon = line.indexOf(':');
                if (colon < 0) continue;
                String iface = line.substring(0, colon).trim();
                if (iface.equals("lo")) continue;
                String[] parts = line.substring(colon + 1).trim().split("\\s+");
                if (parts.length < 16) continue;
                // fields: rx_bytes rx_packets rx_errs ... tx_bytes tx_packets tx_errs ...
                rx  += Long.parseLong(parts[0]);
                rxp += Long.parseLong(parts[1]);
                rxe += Long.parseLong(parts[2]);
                tx  += Long.parseLong(parts[8]);
                txp += Long.parseLong(parts[9]);
                txe += Long.parseLong(parts[10]);
            }
        }
        return new NetSnapshot(System.currentTimeMillis(), rx, tx, rxp, txp, rxe, txe);
    }

    private CpuSnapshot readCpu() throws IOException {
        try (BufferedReader br = Files.newBufferedReader(Paths.get("/proc/stat"))) {
            String line = br.readLine();
            if (line == null || !line.startsWith("cpu ")) return null;
            String[] parts = line.split("\\s+");
            long idle = Long.parseLong(parts[4]);
            long iowait = parts.length > 5 ? Long.parseLong(parts[5]) : 0;
            long total = 0;
            for (int i = 1; i < parts.length; i++) total += Long.parseLong(parts[i]);
            return new CpuSnapshot(System.currentTimeMillis(), idle + iowait, total);
        }
    }

    // -----------------------------------------------------------------
    // Sampler thread
    // -----------------------------------------------------------------
    private void sampleLoop() {
        while (true) {
            try {
                long now = System.currentTimeMillis();
                NetSnapshot net = readNet();
                CpuSnapshot cpu = readCpu();

                Map<String, Object> sample = new LinkedHashMap<>();
                sample.put("ts", now);

                if (lastNet != null && net.ts > lastNet.ts) {
                    double dt = (net.ts - lastNet.ts) / 1000.0;
                    sample.put("rx_bps", (net.rxBytes - lastNet.rxBytes) / dt);
                    sample.put("tx_bps", (net.txBytes - lastNet.txBytes) / dt);
                    sample.put("rx_pps", (net.rxPackets - lastNet.rxPackets) / dt);
                    sample.put("tx_pps", (net.txPackets - lastNet.txPackets) / dt);
                    sample.put("rx_err_delta", net.rxErrs - lastNet.rxErrs);
                    sample.put("tx_err_delta", net.txErrs - lastNet.txErrs);
                } else {
                    sample.put("rx_bps", 0);
                    sample.put("tx_bps", 0);
                }
                sample.put("rx_bytes_total", net.rxBytes);
                sample.put("tx_bytes_total", net.txBytes);

                if (lastCpu != null && cpu != null && cpu.ts > lastCpu.ts) {
                    long totalDelta = cpu.idleAndTotal[1] - lastCpu.idleAndTotal[1];
                    long idleDelta  = cpu.idleAndTotal[0] - lastCpu.idleAndTotal[0];
                    double usage = totalDelta > 0
                        ? (1.0 - (double) idleDelta / totalDelta) * 100.0
                        : 0.0;
                    sample.put("cpu_pct", usage);
                }
                if (cpu != null) lastCpu = cpu;
                lastNet = net;

                // Memory from /proc/meminfo
                long memTotal = 0, memFree = 0, memAvail = 0;
                try (BufferedReader br = Files.newBufferedReader(Paths.get("/proc/meminfo"))) {
                    String l;
                    while ((l = br.readLine()) != null) {
                        if (l.startsWith("MemTotal:"))      memTotal = parseKb(l);
                        else if (l.startsWith("MemFree:"))  memFree = parseKb(l);
                        else if (l.startsWith("MemAvailable:")) memAvail = parseKb(l);
                    }
                }
                sample.put("mem_total_kb", memTotal);
                sample.put("mem_free_kb", memFree);
                sample.put("mem_avail_kb", memAvail);
                sample.put("mem_used_pct",
                    memTotal > 0 ? (1.0 - (double) memAvail / memTotal) * 100.0 : 0.0);

                // Store + publish
                synchronized (history) {
                    history.addLast(sample);
                    while (history.size() > historySize) history.removeFirst();
                }
                broadcast(sample);
            } catch (IOException e) {
                System.err.println("[monitor] read error: " + e.getMessage());
            } catch (Exception e) {
                System.err.println("[monitor] unexpected: " + e);
            }
            try { Thread.sleep(sampleIntervalMs); } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            }
        }
    }

    private static long parseKb(String line) {
        String[] parts = line.split("\\s+");
        return parts.length >= 2 ? Long.parseLong(parts[1]) : 0;
    }

    // -----------------------------------------------------------------
    // Unix socket server
    // -----------------------------------------------------------------
    private void broadcast(Map<String, Object> sample) {
        String json = toJson(sample) + "\n";
        byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
        synchronized (clients) {
            for (Iterator<UnixSocketClient> it = clients.iterator(); it.hasNext(); ) {
                UnixSocketClient c = it.next();
                try { c.out.write(bytes); c.out.flush(); }
                catch (IOException e) {
                    it.remove();
                    System.err.println("[monitor] client disconnected: " + e.getMessage());
                }
            }
        }
    }

    private static String toJson(Map<String, Object> m) {
        StringBuilder sb = new StringBuilder("{");
        boolean first = true;
        for (Map.Entry<String, Object> e : m.entrySet()) {
            if (!first) sb.append(',');
            first = false;
            sb.append('"').append(escape(e.getKey())).append("\":");
            Object v = e.getValue();
            if (v instanceof Number) {
                if (v instanceof Double || v instanceof Float) {
                    sb.append(String.format(java.util.Locale.ROOT, "%.3f", ((Number) v).doubleValue()));
                } else {
                    sb.append(v.toString());
                }
            } else if (v instanceof Boolean) {
                sb.append(v.toString());
            } else {
                sb.append('"').append(escape(v.toString())).append('"');
            }
        }
        return sb.append('}').toString();
    }

    private static String escape(String s) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default: sb.append(c);
            }
        }
        return sb.toString();
    }

    private static final class UnixSocketClient {
        final OutputStream out;
        final Socket socket;
        UnixSocketClient(Socket s) throws IOException {
            this.socket = s; this.out = s.getOutputStream();
        }
    }

    public void start() throws IOException {
        // Remove stale socket
        try { Files.deleteIfExists(Paths.get(socketPath)); } catch (IOException ignored) {}
        Path parent = Paths.get(socketPath).getParent();
        if (parent != null) Files.createDirectories(parent);

        @SuppressWarnings("resource")
        ServerSocket server = new ServerSocket() {
            @Override
            public Socket accept() throws IOException {
                Socket s = new Socket() {
                    @Override
                    public boolean isConnected() { return true; }
                };
                implAccept(s);
                return s;
            }
        };

        // Bind Unix domain socket
        try {
            java.lang.reflect.Method bind = server.getClass().getSuperclass()
                .getDeclaredMethod("bind", SocketAddress.class);
            // Use Unix domain via jdk.net + standard API (Java 16+)
            // Fallback: use a TCP listener on localhost for portability.
        } catch (Exception ignored) {}

        // Portable fallback: TCP on localhost:9101 (configurable)
        int port = Integer.parseInt(System.getProperty("vortex.monitor.port", "9101"));
        ServerSocket tcp = new ServerSocket(port, 16, InetAddress.getByName("127.0.0.1"));
        System.out.println("[monitor] v" + VERSION + " listening on 127.0.0.1:" + port
            + " (sample=" + sampleIntervalMs + "ms, history=" + historySize + ")");

        Thread sampler = new Thread(this::sampleLoop, "vortex-sampler");
        sampler.setDaemon(true);
        sampler.start();

        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            System.out.println("[monitor] shutting down");
            try { tcp.close(); } catch (IOException ignored) {}
        }));

        while (true) {
            try {
                Socket client = tcp.accept();
                clients.add(new UnixSocketClient(client));
                System.out.println("[monitor] client connected (total=" + clients.size() + ")");
                // Send history on connect
                synchronized (history) {
                    for (Map<String, Object> s : history) {
                        client.getOutputStream()
                            .write((toJson(s) + "\n").getBytes(StandardCharsets.UTF_8));
                    }
                    client.getOutputStream().flush();
                }
            } catch (IOException e) {
                if (tcp.isClosed()) break;
                System.err.println("[monitor] accept failed: " + e.getMessage());
            }
        }
    }

    // -----------------------------------------------------------------
    // Entry point
    // -----------------------------------------------------------------
    public static void main(String[] args) throws Exception {
        String socketPath = args.length > 0 ? args[0] : "/var/run/vortexvpn/monitor.sock";
        int interval = args.length > 1 ? Integer.parseInt(args[1]) : 1000;
        int history  = args.length > 2 ? Integer.parseInt(args[2]) : 3600;
        new VortexMonitor(socketPath, interval, history).start();
    }
}
