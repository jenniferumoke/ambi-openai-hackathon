using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Net.Http;
using System.Text.Json;
namespace AmbiCompanion;

public sealed class BackendService(string bundle, string dataDirectory, string? backendOrigin = null) : IDisposable
{
    private readonly string origin = backendOrigin ?? CompanionPolicy.Origin;
    private readonly HttpClient http = new() { Timeout = TimeSpan.FromSeconds(2) };
    private Process? process;
    private StreamWriter? log;
    private readonly SemaphoreSlim logLock = new(1);
    public string RuntimeDirectory => Path.Combine(dataDirectory, "backend");
    public bool Owned => process is { HasExited: false };
    public async Task<bool> ProbeAsync()
    {
        try
        {
            using var response = await http.GetAsync(origin + "/api/bootstrap");
            if (!response.IsSuccessStatusCode) return false;
            using var json = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            var root = json.RootElement;
            return root.TryGetProperty("token", out var token) && token.ValueKind == JsonValueKind.String
                && root.TryGetProperty("state", out var state) && state.TryGetProperty("observations", out _)
                && state.TryGetProperty("memories", out _) && state.TryGetProperty("status", out _);
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or JsonException) { return false; }
    }
    private async Task<bool> PortOccupiedAsync()
    {
        using var tcp = new TcpClient();
        try { await tcp.ConnectAsync("127.0.0.1", new Uri(origin).Port).WaitAsync(TimeSpan.FromSeconds(1)); return true; }
        catch { return false; }
    }
    private void PrepareRuntime()
    {
        var source = Path.Combine(bundle, "backend");
        var files = JsonSerializer.Deserialize<string[]>(File.ReadAllText(Path.Combine(source, "files.json"))) ?? [];
        foreach (var relative in files)
        {
            var from = Path.GetFullPath(Path.Combine(source, relative));
            var to = Path.GetFullPath(Path.Combine(RuntimeDirectory, relative));
            if (!from.StartsWith(Path.GetFullPath(source) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                || !to.StartsWith(Path.GetFullPath(RuntimeDirectory) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                || Path.GetFileName(relative) == ".env" || relative.Split('/', '\\').Any(p => p is "data" or ".venv"))
                throw new InvalidDataException("Invalid bundled backend file.");
            Directory.CreateDirectory(Path.GetDirectoryName(to)!);
            File.Copy(from, to, true);
        }
    }
    public async Task<string?> StartAsync(string? key)
    {
        if (await ProbeAsync()) return null;
        if (await PortOccupiedAsync()) return "Port 8767 is already in use by another service. Ambi will not replace it.";
        if (Owned) return "The local service is still preparing. Please wait, then choose Connection → Reload.";
        await CloseLogAsync();
        process?.Dispose();
        process = null;
        PrepareRuntime();
        var frozen = Path.Combine(bundle, "service", "AmbiService.exe");
        var python = Path.Combine(bundle, "runtime", "python.exe");
        var executable = File.Exists(frozen) ? frozen : File.Exists(python) ? python : Path.Combine(bundle, "tools", "uv.exe");
        if (!File.Exists(executable)) return "The bundled runtime is missing. Extract the complete app folder again.";
        Directory.CreateDirectory(dataDirectory);
        log = new StreamWriter(Path.Combine(dataDirectory, "service.log"), false) { AutoFlush = true };
        var start = new ProcessStartInfo(executable) { WorkingDirectory = RuntimeDirectory, UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
        var args = File.Exists(frozen) ? new[] { "--port", "8767" } : File.Exists(python) ? new[] { "companion_service.py", "--port", "8767" } : new[] { "run", "--locked", "--python", "3.12", "python", "windows_service.py" };
        foreach (var argument in args) start.ArgumentList.Add(argument);
        start.Environment["AMBI_DATA_DIR"] = Path.Combine(dataDirectory, "data");
        var codex = Path.Combine(bundle, "Codex", "bin", "codex.exe");
        if (File.Exists(codex)) start.Environment["AMBI_CODEX_BIN"] = codex;
        if (!string.IsNullOrWhiteSpace(key)) start.Environment["OPENAI_API_KEY"] = key;
        start.Environment["PYTHONUNBUFFERED"] = "1";
        process = new Process { StartInfo = start };
        if (!process.Start()) return "The Python service could not start.";
        _ = CopyLogAsync(process.StandardOutput, log);
        _ = CopyLogAsync(process.StandardError, log);
        // First run may need the pinned Python interpreter and dependencies.
        for (var i = 0; i < 480; i++)
        {
            if (process.HasExited) return "The local service exited. See Connection → Open Service Folder and service.log.";
            if (await ProbeAsync()) return null;
            await Task.Delay(500);
        }
        return "The service is still preparing. Use Connection → Reload in a moment, or inspect service.log.";
    }
    private async Task CopyLogAsync(StreamReader reader, StreamWriter writer)
    {
        try
        {
            while (await reader.ReadLineAsync() is { } line)
            {
                await logLock.WaitAsync();
                // Capture the launch's writer: an old reader must never write
                // late output into the next launch's log.
                try { await writer.WriteLineAsync(line); }
                finally { logLock.Release(); }
            }
        }
        catch (Exception e) when (e is IOException or ObjectDisposedException or InvalidOperationException) { }
    }
    private async Task CloseLogAsync()
    {
        await logLock.WaitAsync();
        try { log?.Dispose(); log = null; }
        finally { logLock.Release(); }
    }
    public async Task StopOwnedAsync(bool sessionOwned, bool taskOwned = false, string? clientId = null)
    {
        if (sessionOwned || taskOwned)
        {
            try
            {
                using var json = JsonDocument.Parse(await http.GetStringAsync(origin + "/api/bootstrap"));
                using var stopClient = new HttpClient { Timeout = TimeSpan.FromSeconds(12) };
                foreach (var action in (taskOwned ? new[] { "stop-task" } : Array.Empty<string>()).Concat(sessionOwned ? new[] { "stop" } : Array.Empty<string>())) {
                using var request = new HttpRequestMessage(HttpMethod.Post, origin + "/api/" + action);
                request.Headers.Add("X-Ambi-Token", json.RootElement.GetProperty("token").GetString());
                request.Content = new StringContent(action == "stop-task" ? JsonSerializer.Serialize(new { client_id = clientId }) : "{}", System.Text.Encoding.UTF8, "application/json");
                using var response = await stopClient.SendAsync(request);
                }
                await Task.Delay(200);
            }
            catch { /* Only the app-owned process below may be terminated. */ }
        }
        if (Owned)
        {
            process!.Kill(entireProcessTree: true);
            await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(5));
        }
        // Also release a writer left behind by an already-exited child.
        // Otherwise the next launch fails reopening service.log on Windows.
        await CloseLogAsync();
    }
    public void Dispose() { process?.Dispose(); log?.Dispose(); http.Dispose(); }
}
