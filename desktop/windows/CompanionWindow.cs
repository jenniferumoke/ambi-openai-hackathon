using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;
namespace AmbiCompanion;

public sealed class CompanionWindow : Window
{
    private readonly WebView2 web = new();
    private readonly Grid content = new();
    private readonly StackPanel recovery = new() { VerticalAlignment = VerticalAlignment.Center, HorizontalAlignment = HorizontalAlignment.Center, MaxWidth = 360, Margin = new Thickness(30) };
    private readonly TextBlock notice = new() { TextWrapping = TextWrapping.Wrap, TextAlignment = TextAlignment.Center, Margin = new Thickness(0, 12, 0, 18), Foreground = Brushes.DimGray };
    private readonly Button startServiceButton = new() { Content = "Start local service", Padding = new Thickness(18, 10, 18, 10), HorizontalAlignment = HorizontalAlignment.Center };
    private readonly string dataDirectory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AmbiCompanion");
    private readonly BackendService service;
    private CompanionPreferences preferences = new();
    private readonly ScreenFrame screenFrame = new();
    private JsonElement state;
    private readonly MenuItem statusItem = new() { Header = "Local service offline", IsEnabled = false };
    private readonly MenuItem sessionItem = new() { Header = "Start Session", InputGestureText = "Ctrl+S" };
    private readonly MenuItem taskItem = new() { Header = "Stop Computer Task", InputGestureText = "Ctrl+." };
    private readonly MenuItem micItem = new() { Header = "Mute Microphone", InputGestureText = "Ctrl+M" };
    private readonly MenuItem focusItem = new() { Header = "Focus Mode", IsCheckable = true };
    private readonly MenuItem screenItem = new() { Header = "Screen Context — not available in this Windows build", IsCheckable = true, IsEnabled = false };
    private readonly MenuItem topItem = new() { Header = "Always on Top", IsCheckable = true };
    private bool ownsSession, closing, serviceBusy, expanded, setupOpen;
    private (double Width, double Height)? compactSize, setupSize;
    private string? launchKey;
    private string lastError = "";
    private readonly System.Windows.Threading.DispatcherTimer reconnect = new() { Interval = TimeSpan.FromSeconds(3) };
    public CompanionWindow()
    {
        Title = "Ambi"; Width = 560; Height = 600; MinWidth = 360; MinHeight = 440;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        Icon = BitmapFrame.Create(new Uri(Path.Combine(AppContext.BaseDirectory, "icons", "ambi.ico")));
        Directory.CreateDirectory(dataDirectory);
        try
        {
            using var json = JsonDocument.Parse(File.ReadAllText(Path.Combine(dataDirectory, "preferences.json")));
            preferences = CompanionPreferences.Parse(json.RootElement) ?? new();
        }
        catch (Exception e) when (e is IOException or JsonException or UnauthorizedAccessException) { }
        Topmost = preferences.AlwaysOnTop;
        service = new BackendService(AppContext.BaseDirectory, dataDirectory);
        var layout = new DockPanel();
        var menu = BuildMenu(); DockPanel.SetDock(menu, Dock.Top); layout.Children.Add(menu);
        var image = new Image { Source = new BitmapImage(new Uri(Path.Combine(AppContext.BaseDirectory, "icons", "ambi.png"))), Width = 180, Height = 180, Margin = new Thickness(0, 0, 0, 10) };
        recovery.Children.Add(image);
        recovery.Children.Add(new TextBlock { Text = "A little company.", FontSize = 24, FontWeight = FontWeights.SemiBold, TextAlignment = TextAlignment.Center });
        notice.Text = "Start Ambi’s local service to bring your companion here. Voice and screen context stay off until you choose them.";
        recovery.Children.Add(notice); recovery.Children.Add(startServiceButton);
        content.Children.Add(web); content.Children.Add(recovery); layout.Children.Add(content); Content = layout;
        web.Visibility = Visibility.Collapsed;
        startServiceButton.Click += async (_, _) => await StartServiceAsync();
        Loaded += async (_, _) => await InitializeAsync();
        Closing += OnClosing;
        screenFrame.Stop = () => _ = CommandAsync("stop-task");
        reconnect.Tick += async (_, _) => { if (web.Visibility != Visibility.Visible && !serviceBusy && await service.ProbeAsync()) LoadCompanion(); };
    }
    private Menu BuildMenu()
    {
        var menu = new Menu();
        MenuItem Group(string title) { var group = new MenuItem { Header = title }; menu.Items.Add(group); return group; }
        void Add(MenuItem parent, string title, Action action, string? shortcut = null)
        {
            var item = new MenuItem { Header = title, InputGestureText = shortcut ?? "" };
            item.Click += (_, _) => action(); parent.Items.Add(item);
        }
        var session = Group("_Session"); session.Items.Add(statusItem); session.Items.Add(new Separator());
        sessionItem.Click += async (_, _) => await CommandAsync("toggle-session"); session.Items.Add(sessionItem);
        taskItem.Click += async (_, _) => await CommandAsync("stop-task"); session.Items.Add(taskItem);
        micItem.Click += async (_, _) => await CommandAsync("microphone"); session.Items.Add(micItem);
        focusItem.Click += async (_, _) => await CommandAsync("focus"); session.Items.Add(focusItem);
        screenItem.Click += async (_, _) => await JsAsync("screenContext", screenItem.IsChecked); session.Items.Add(screenItem);
        Add(session, "Review Suggestion…", ReviewSuggestion, "Ctrl+R");
        Add(session, "Quit Ambi", Close, "Alt+F4");
        var view = Group("_View");
        Add(view, "Show or Hide Activity", () => _ = JsAsync("showActivity"), "Ctrl+D");
        Add(view, "Customize Ambi…", () => _ = JsAsync("showSetup"));
        Add(view, "White Background", () => SetPreferences(preferences with { Background = "white" }));
        Add(view, "Black Background", () => SetPreferences(preferences with { Background = "black" }));
        Add(view, "Navy Background", () => SetPreferences(preferences with { Background = "navy" }));
        Add(view, "Preview Whole-Screen Frame", () => screenFrame.SetPreview(true));
        foreach (var (title, width) in new[] { ("Small Window", 260d), ("Medium Window", 480d), ("Large Window", 720d) })
            Add(view, title, () => { if (!expanded && !setupOpen) { Width = width; Height = Math.Max(240, width * .84); } });
        Add(view, "Smaller Character", () => SetPreferences(preferences with { Scale = Math.Max(.35, preferences.Scale - .1) }));
        Add(view, "Larger Character", () => SetPreferences(preferences with { Scale = Math.Min(.95, preferences.Scale + .1) }));
        topItem.IsChecked = Topmost;
        topItem.Click += (_, _) => SetPreferences(preferences with { AlwaysOnTop = topItem.IsChecked }); view.Items.Add(topItem);
        var connection = Group("_Connection");
        Add(connection, "Reload", () => _ = ReloadAsync(), "Ctrl+L");
        Add(connection, "Start Local Service", () => _ = StartServiceAsync());
        Add(connection, "Configure API Key for This Launch…", ConfigureKey);
        Add(connection, "Open Full Controls in Browser", () => OpenPath(CompanionPolicy.Origin + "/"));
        Add(connection, "Open Service Folder", () => { Directory.CreateDirectory(dataDirectory); OpenPath(dataDirectory); });
        Add(connection, "Setup & Connections…", () => _ = JsAsync("showConnections"));
        Add(connection, "Check for Updates…", () => OpenPath("https://github.com/jenniferumoke/ambi-openai-hackathon/releases"));
        Add(connection, "Show Connection Details…", () => MessageBox.Show(this, $"Service: {CompanionPolicy.Origin}\nStatus: {StringState("status", "offline")}\nMode: {StringState("mode", "unavailable")}\nAPI key present: {BoolState("apiConfigured")}\nApp-owned service: {service.Owned}\n\n{lastError}", "Ambi connection"));
        session.SubmenuOpened += (_, _) => UpdateMenu();
        return menu;
    }
    private async Task InitializeAsync()
    {
        try
        {
            var environment = await CoreWebView2Environment.CreateAsync(null, Path.Combine(dataDirectory, "WebView2"));
            await web.EnsureCoreWebView2Async(environment);
            var core = web.CoreWebView2;
            core.Settings.AreDevToolsEnabled = false; core.Settings.AreDefaultContextMenusEnabled = false;
            core.Settings.IsStatusBarEnabled = false; core.Settings.IsZoomControlEnabled = false;
            core.PermissionRequested += (_, e) => e.State = CoreWebView2PermissionState.Deny;
            core.NewWindowRequested += (_, e) => e.Handled = true;
            core.DownloadStarting += (_, e) => e.Cancel = true;
            core.NavigationStarting += (_, e) => { if (!CompanionPolicy.Trusted(e.Uri)) e.Cancel = true; };
            core.FrameNavigationStarting += (_, e) => e.Cancel = true;
            core.WebMessageReceived += OnMessage;
            await core.AddScriptToExecuteOnDocumentCreatedAsync("if(window===window.top){window.webkit={messageHandlers:{ambi:{postMessage:(message)=>window.chrome.webview.postMessage(message)}}};}");
            core.NavigationCompleted += async (_, e) =>
            {
                if (e.IsSuccess) { await ApplyPreferencesAsync(); await JsAsync("screenContext", false); }
                else ShowRecovery("The companion page could not load. Start the local service, then choose Connection → Reload.");
            };
            KeyEventHandler shortcuts = (_, e) =>
            {
                if (e.Handled || (Keyboard.Modifiers & ModifierKeys.Control) == 0) return;
                Action? action = KeyInterop.VirtualKeyFromKey(e.Key) switch
                {
                    68 => () => _ = JsAsync("showActivity"),
                    83 => () => _ = CommandAsync("toggle-session"),
                    77 => () => _ = CommandAsync("microphone"),
                    70 => () => _ = CommandAsync("focus"),
                    82 => ReviewSuggestion,
                    76 => () => _ = ReloadAsync(),
                    190 => () => _ = CommandAsync("stop-task"),
                    _ => null,
                };
                if (action is not null) { e.Handled = true; Dispatcher.BeginInvoke(action); }
            };
            PreviewKeyDown += shortcuts;
            web.PreviewKeyDown += shortcuts;
            await ReloadAsync(); reconnect.Start();
        }
        catch (Exception e)
        {
            lastError = e.GetType().Name;
            ShowRecovery("Ambi could not initialize WebView2. Check that the Microsoft Edge WebView2 Runtime is installed, then reopen Ambi.");
        }
    }
    private void LoadCompanion()
    {
        screenFrame.Reset();
        if (web.CoreWebView2 is null) return;
        recovery.Visibility = Visibility.Collapsed; web.Visibility = Visibility.Visible;
        web.CoreWebView2.Navigate(CompanionPolicy.CompanionUrl);
    }
    private async Task ReloadAsync()
    {
        if (await service.ProbeAsync()) LoadCompanion();
        else ShowRecovery("Ambi’s local service is offline. Start it below. The first run prepares Python and its pinned dependencies.");
    }
    private void ShowRecovery(string text) { web.Visibility = Visibility.Collapsed; recovery.Visibility = Visibility.Visible; notice.Text = text; }
    private async Task StartServiceAsync()
    {
        if (serviceBusy) return;
        serviceBusy = true; startServiceButton.IsEnabled = false;
        ShowRecovery("Preparing your local companion… The first run can take a few minutes. No microphone, camera, or screen capture is starting.");
        try
        {
            var error = await service.StartAsync(launchKey);
            if (error is null) LoadCompanion(); else { lastError = error; ShowRecovery(error); }
        }
        catch (Exception e) { lastError = e.GetType().Name; ShowRecovery("Ambi could not start its local service. Open the service folder from the Connection menu and check service.log."); }
        finally { serviceBusy = false; startServiceButton.IsEnabled = true; }
    }
    private async Task JsAsync(string method, params object?[] args)
    {
        if (web.CoreWebView2 is null || !CompanionPolicy.Trusted(web.Source?.ToString())) return;
        try { await web.CoreWebView2.ExecuteScriptAsync(CompanionPolicy.Call(method, args)); }
        catch (InvalidOperationException) { }
    }
    private Task CommandAsync(string name, string? value = null) => value is null ? JsAsync("command", name) : JsAsync("command", name, value);
    private async Task ApplyPreferencesAsync()
    {
        Background = preferences.Background switch { "white" => Brushes.White, "black" => Brushes.Black, _ => new SolidColorBrush(Color.FromRgb(13, 27, 42)) };
        Topmost = preferences.AlwaysOnTop; topItem.IsChecked = Topmost;
        await JsAsync("configure", new { preferences.DisplayName, preferences.Color, preferences.Background, preferences.Scale, preferences.Animated, needsSetup = !preferences.Completed });
    }
    private void SetPreferences(CompanionPreferences value)
    {
        preferences = value;
        File.WriteAllText(Path.Combine(dataDirectory, "preferences.json"), JsonSerializer.Serialize(preferences, CompanionPolicy.Json));
        _ = ApplyPreferencesAsync();
    }
    private async void OnMessage(object? sender, CoreWebView2WebMessageReceivedEventArgs e)
    {
        if (!CompanionPolicy.Trusted(e.Source)) return;
        try
        {
            using var document = JsonDocument.Parse(e.WebMessageAsJson);
            var body = document.RootElement;
            switch (body.GetProperty("type").GetString())
            {
                case "state":
                    state = body.Clone(); ownsSession = BoolState("sessionOwned"); UpdateMenu();
                    screenFrame.Update(BoolState("connected"), BoolState("jobRunning")); break;
                case "browser-chat":
                    var provider = body.GetProperty("provider").GetString();
                    var chatUrl = provider switch { "chatgpt" => "https://chatgpt.com/", "claude" => "https://claude.ai/", "gemini" => "https://gemini.google.com/", _ => null };
                    if (chatUrl is null || !body.TryGetProperty("draft", out var draftValue) || draftValue.ValueKind != JsonValueKind.String) break;
                    var draft = draftValue.GetString() ?? "";
                    if (draft.Length > 4000) break;
                    if (!string.IsNullOrWhiteSpace(draft)) Clipboard.SetText(draft);
                    OpenPath(chatUrl);
                    break;
                case "reconnect-driver":
                    if (serviceBusy || !service.Owned || !BoolState("connected") || BoolState("jobRunning") || StringState("status", "") is not ("idle" or "error"))
                    { MessageBox.Show(this, "End active voice and tasks first. Only Ambi’s own idle service can be reconnected.", "Ambi"); break; }
                    serviceBusy = true;
                    try { await service.StopOwnedAsync(false); }
                    finally { serviceBusy = false; }
                    await StartServiceAsync();
                    break;
                case "configure-voice": ConfigureKey(); break;
                case "choose-workspace":
                    var picker = new Microsoft.Win32.OpenFolderDialog { Title = "Choose Ambi’s working folder" };
                    if (picker.ShowDialog(this) == true) _ = JsAsync("selectWorkspace", picker.FolderName);
                    break;
                case "open-permissions": OpenPath("ms-settings:privacy-microphone"); break;
                case "copy-diagnostics":
                    var text = body.GetProperty("text").GetString();
                    if (text is not null && text.Length <= 8000) Clipboard.SetText(text);
                    break;
                case "open-codex-login":
                    var url = body.GetProperty("url").GetString();
                    if (Uri.TryCreate(url, UriKind.Absolute, out var login) && login.Scheme == "https" && login.Host == "auth.openai.com" && login.UserInfo == "") OpenPath(url!);
                    break;
                case "frame-color": screenFrame.SetColor(body.GetProperty("hex").GetString()); break;
                case "frame-preview": screenFrame.SetPreview(body.GetProperty("enabled").GetBoolean()); break;
                case "error": lastError = body.GetProperty("message").GetString() ?? "Connection error"; break;
                case "layout": SetExpanded(body.GetProperty("expanded").GetBoolean()); break;
                case "setup-layout": SetSetupOpen(body.GetProperty("open").GetBoolean()); break;
                case "preferences":
                    var validated = CompanionPreferences.Parse(body.GetProperty("value"));
                    if (validated is not null) SetPreferences(validated with { Completed = true, AlwaysOnTop = preferences.AlwaysOnTop });
                    break;
            }
        }
        catch (Exception exc) when (exc is JsonException or InvalidOperationException or KeyNotFoundException or IOException) { }
    }
    private void SetExpanded(bool value)
    {
        if (expanded == value) return;
        expanded = value;
        if (setupOpen) return;
        MinWidth = value ? 680 : 360; MinHeight = 440;
        if (value) { compactSize = (Width, Height); ResizeInsideScreen(940, Math.Max(600, Height)); }
        else if (compactSize is { } size) ResizeInsideScreen(size.Width, size.Height);
    }
    private void SetSetupOpen(bool value)
    {
        if (setupOpen == value) return;
        setupOpen = value;
        if (value) { setupSize = (Width, Height); ResizeInsideScreen(980, 720); }
        else if (setupSize is { } size) { ResizeInsideScreen(expanded ? 940 : size.Width, expanded ? Math.Max(600, size.Height) : size.Height); }
    }
    private void ResizeInsideScreen(double width, double height)
    {
        var area = SystemParameters.WorkArea;
        Width = Math.Min(width, area.Width); Height = Math.Min(height, area.Height);
        Left = Math.Clamp(Left, area.Left, Math.Max(area.Left, area.Right - Width));
        Top = Math.Clamp(Top, area.Top, Math.Max(area.Top, area.Bottom - Height));
    }
    private bool BoolState(string name) => state.ValueKind == JsonValueKind.Object && state.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.True;
    private string StringState(string name, string fallback) => state.ValueKind == JsonValueKind.Object && state.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? fallback : fallback;
    private void UpdateMenu()
    {
        var connected = BoolState("connected"); var status = StringState("status", "offline");
        statusItem.Header = $"{status} · {(StringState("mode", "") == "ellis_demo" ? "Ellis demo" : "Personal memory")}";
        sessionItem.Header = status is "connected" or "connecting" ? "End Session" : "Start Session";
        sessionItem.IsEnabled = connected && status != "stopping";
        taskItem.IsEnabled = connected && BoolState("jobRunning"); micItem.IsEnabled = connected; focusItem.IsEnabled = connected;
        micItem.Header = BoolState("microphoneEnabled") ? "Mute Microphone" : "Unmute Microphone";
        focusItem.IsChecked = BoolState("focus");
    }
    private async void ReviewSuggestion()
    {
        if (state.ValueKind != JsonValueKind.Object || !state.TryGetProperty("suggestion", out var suggestion) || suggestion.ValueKind != JsonValueKind.Object) return;
        var text = suggestion.GetProperty("text").GetString(); var id = suggestion.GetProperty("id").GetString();
        if (id is null) return;
        var accept = MessageBox.Show(this, text, "A thought from Ambi — help with this task?", MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No) == MessageBoxResult.Yes;
        await CommandAsync(accept ? "accept" : "dismiss", id);
    }
    private void ConfigureKey()
    {
        if (serviceBusy || BoolState("jobRunning") || BoolState("connected") && StringState("status", "") is "connected" or "connecting" or "stopping")
        { MessageBox.Show(this, "End the current voice session before changing its API configuration.", "Ambi"); return; }
        if (web.Visibility == Visibility.Visible && !service.Owned)
        { MessageBox.Show(this, "The service was started elsewhere. Configure its private .env locally, then restart that service.", "Ambi"); return; }
        var dialog = new Window { Title = "Ambi API key", Owner = this, Width = 420, Height = 250, ResizeMode = ResizeMode.NoResize, WindowStartupLocation = WindowStartupLocation.CenterOwner };
        var panel = new StackPanel { Margin = new Thickness(24) }; var field = new PasswordBox { MaxLength = 512, Margin = new Thickness(0, 14, 0, 14) };
        panel.Children.Add(new TextBlock { Text = "Enter your OpenAI API key. It stays in memory until Ambi closes; the local Python service uses it for OpenAI requests.", TextWrapping = TextWrapping.Wrap }); panel.Children.Add(field);
        var save = new Button { Content = "Use for this launch", Padding = new Thickness(12, 8, 12, 8), HorizontalAlignment = HorizontalAlignment.Right };
        save.Click += async (_, _) =>
        {
            if (string.IsNullOrWhiteSpace(field.Password)) return;
            launchKey = field.Password.Trim(); field.Clear(); dialog.Close();
            await service.StopOwnedAsync(false); await StartServiceAsync();
        };
        panel.Children.Add(save); dialog.Content = panel; dialog.ShowDialog();
    }
    private static void OpenPath(string path) => Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
    private async void OnClosing(object? sender, CancelEventArgs e)
    {
        if (closing) return;
        e.Cancel = true; closing = true; reconnect.Stop(); screenFrame.Dispose(); launchKey = null;
        try { await service.StopOwnedAsync(ownsSession, BoolState("jobOwned"), StringState("ownedJobClientId", "")); }
        catch { /* Never terminate externally owned processes. */ }
        finally { service.Dispose(); web.Dispose(); Close(); }
    }
}
