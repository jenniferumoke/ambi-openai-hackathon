using System.Text.Json;
using AmbiCompanion;
int checks = 0;
void Check(bool pass, string name) { if (!pass) throw new Exception(name); checks++; }
Check(CompanionPolicy.Trusted("http://127.0.0.1:8767/companion.html"), "Exact companion origin");
foreach (var url in new[] { "https://127.0.0.1:8767/companion.html", "http://127.0.0.1:87670/companion.html", "http://127.0.0.1.evil.test:8767/companion.html", "http://localhost:8767/companion.html", "http://127.0.0.1:8767/", "http://127.0.0.1:8767/companion.html?next=https://evil.test", "http://x@127.0.0.1:8767/companion.html", "file:///tmp/companion.html", "about:blank" }) Check(!CompanionPolicy.Trusted(url), "Reject " + url);
var hostile = "');window.bad=true;//\n\u2028";
var call = CompanionPolicy.Call("command", "accept", hostile);
Check(!call.Contains("window.bad=true;//\n"), "Serialize hostile strings");
var start = call.IndexOf("(...", StringComparison.Ordinal) + 4;
var payload = call[start..^1];
var bridgeArgs = JsonSerializer.Deserialize<string[]>(payload)!;
Check(bridgeArgs[1] == hostile, "Bridge preserves argument data");
try { CompanionPolicy.Call("arbitraryMethod"); throw new Exception("Unknown method allowed"); } catch (ArgumentException) { checks++; }
CompanionPreferences? Parse(string value) { using var d = JsonDocument.Parse(value); return CompanionPreferences.Parse(d.RootElement); }
Check(Parse("{\"displayName\":\"A little friend\",\"color\":\"rose\",\"scale\":0.6}")?.DisplayName == "A little friend", "Accept valid customization");
foreach (var value in new[] { "{\"displayName\":\"\"}", "{\"displayName\":null}", "{\"color\":\"unknown\"}", "{\"scale\":100}", "{\"scale\":\"bad\"}", "{\"background\":\"url(evil)\"}", "null" }) Check(Parse(value) is null, "Reject invalid settings " + value);
Console.WriteLine($"{checks} native policy checks passed.");
// A real local HTTP server verifies that an external service is reused and
// never terminated or sent stop unless this companion explicitly owns a session.
var reserved = new System.Net.Sockets.TcpListener(System.Net.IPAddress.Loopback, 0);
reserved.Start(); var port = ((System.Net.IPEndPoint)reserved.LocalEndpoint).Port; reserved.Stop();
using var listener = new System.Net.HttpListener();
var origin = $"http://127.0.0.1:{port}"; listener.Prefixes.Add(origin + "/"); listener.Start();
int stopRequests = 0;
var serve = Task.Run(async () => {
    while (listener.IsListening) {
        try {
            var context = await listener.GetContextAsync();
            if (context.Request.Url!.AbsolutePath == "/api/stop") Interlocked.Increment(ref stopRequests);
            var body = System.Text.Encoding.UTF8.GetBytes("{\"token\":\"test-only\",\"state\":{\"observations\":{},\"memories\":[],\"status\":\"idle\"}}");
            context.Response.ContentType = "application/json"; context.Response.ContentLength64 = body.Length;
            await context.Response.OutputStream.WriteAsync(body); context.Response.Close();
        } catch (Exception e) when (e is System.Net.HttpListenerException or ObjectDisposedException) { break; }
    }
});
using (var external = new BackendService("not-a-bundle", "unused-test-directory", origin)) {
    Check(await external.StartAsync(null) is null && !external.Owned, "Reuse external service without accessing bundle or spawning a process");
    await external.StopOwnedAsync(false);
    Check(await external.ProbeAsync() && stopRequests == 0, "External session/service left untouched on companion quit");
    await external.StopOwnedAsync(true);
    Check(await external.ProbeAsync() && stopRequests == 1, "Only an explicitly owned session is sent stop; external service remains");
}
listener.Stop(); await serve;
var logDirectory = Path.Combine(Path.GetTempPath(), "ambi-log-regression-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(logDirectory);
try {
    var logPath = Path.Combine(logDirectory, "service.log");
    using var stopped = new BackendService("unused-bundle", logDirectory);
    var writer = new StreamWriter(logPath, false) { AutoFlush = true };
    typeof(BackendService).GetField("log", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.SetValue(stopped, writer);
    await writer.WriteLineAsync("synthetic lifecycle test");
    try { using var before = new FileStream(logPath, FileMode.Open, FileAccess.ReadWrite, FileShare.None); throw new Exception("Fixture did not hold the log"); }
    catch (IOException) { checks++; }
    await stopped.StopOwnedAsync(false);
    using (var reopened = new FileStream(logPath, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
        Check(reopened.Length > 0, "Stopped/exited backend releases log so key setup can restart it");
    await stopped.StopOwnedAsync(false);
    Check(!stopped.Owned, "Repeated idle cleanup remains safe");
} finally { Directory.Delete(logDirectory, true); }
Console.WriteLine($"{checks} total native policy and lifecycle checks passed.");
