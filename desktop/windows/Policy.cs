using System.Text.Json;
using System.Text.Json.Serialization;
namespace AmbiCompanion;

public static class CompanionPolicy
{
    public const string Origin = "http://127.0.0.1:8767";
    public const string CompanionUrl = Origin + "/companion.html";
    public static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase, PropertyNameCaseInsensitive = true };
    private static readonly HashSet<string> Methods = ["command", "appearance", "configure", "screenContext", "showActivity", "showSetup", "showConnections", "selectWorkspace"];
    public static bool Trusted(string? value) => Uri.TryCreate(value, UriKind.Absolute, out var uri)
        && uri.Scheme == "http" && uri.Host == "127.0.0.1" && uri.Port == 8767
        && uri.AbsolutePath == "/companion.html" && uri.Query == "" && uri.Fragment == "" && uri.UserInfo == "";
    public static string Call(string method, params object?[] args)
    {
        if (!Methods.Contains(method)) throw new ArgumentException("Unsupported companion method.");
        return $"window.ambiDesktop?.[{JsonSerializer.Serialize(method)}]?.(...{JsonSerializer.Serialize(args, Json)})";
    }
}

public sealed record CompanionPreferences
{
    public string DisplayName { get; init; } = "Ambi";
    public string Color { get; init; } = "blue";
    public string Background { get; init; } = "navy";
    public double Scale { get; init; } = .78;
    public bool Animated { get; init; } = true;
    public bool Completed { get; init; }
    public bool AlwaysOnTop { get; init; }
    public static CompanionPreferences? Parse(JsonElement value)
    {
        try
        {
            var p = value.Deserialize<CompanionPreferences>(CompanionPolicy.Json);
            if (p is null || p.DisplayName is null || p.Color is null || p.Background is null) return null;
            var name = p.DisplayName.Trim();
            if (name.Length is < 1 or > 24 || name.Any(char.IsControl) || !double.IsFinite(p.Scale) || p.Scale is < .35 or > .95
                || !new[] { "teal", "rose", "butter", "peach", "lilac", "blue" }.Contains(p.Color)
                || p.Background is not ("white" or "black" or "navy")) return null;
            return p with { DisplayName = name };
        }
        catch (JsonException) { return null; }
    }
}
