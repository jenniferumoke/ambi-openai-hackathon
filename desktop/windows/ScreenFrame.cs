using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Effects;
using System.Windows.Threading;
using Microsoft.Win32;

namespace AmbiCompanion;

// Visual feedback only. This grants no screen capture or desktop-control access.
internal sealed class ScreenFrame : IDisposable
{
    private readonly List<Window> windows = [];
    private readonly DispatcherTimer watchdog = new() { Interval = TimeSpan.FromSeconds(1) };
    private readonly Dispatcher dispatcher = Dispatcher.CurrentDispatcher;
    private DateTime heartbeat = DateTime.MinValue;
    private bool active, preview, disposed;
    private Color accent = Color.FromRgb(91, 141, 239);
    public Action? Stop { get; set; }

    public ScreenFrame()
    {
        watchdog.Tick += (_, _) => { if (active && DateTime.UtcNow - heartbeat > TimeSpan.FromSeconds(3)) Reset(); };
        watchdog.Start();
        SystemEvents.DisplaySettingsChanged += DisplaysChanged;
    }
    private void DisplaysChanged(object? sender, EventArgs args) => dispatcher.BeginInvoke(() => { if (!disposed) Rebuild(); });
    public void Update(bool connected, bool running)
    {
        heartbeat = DateTime.UtcNow;
        var next = connected && running;
        if (next == active && (connected || !preview)) return;
        active = next; preview = false; Rebuild();
    }
    public void SetPreview(bool enabled)
    {
        if (preview == enabled) return;
        preview = enabled; Rebuild();
    }
    public void SetColor(string? hex)
    {
        if (hex is null || !Regex.IsMatch(hex, "^#[0-9a-fA-F]{6}$")) return;
        var color = (Color)ColorConverter.ConvertFromString(hex);
        if (accent == color) return;
        accent = color; Rebuild();
    }
    public void Reset() { active = preview = false; Rebuild(); }
    private void Rebuild()
    {
        foreach (var window in windows) window.Close();
        windows.Clear();
        if (disposed || (!active && !preview)) return;
        MonitorCallback callback = (IntPtr monitor, IntPtr hdc, ref NativeRect rect, IntPtr data) => {
            ShowDisplay(rect); return true;
        };
        EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, callback, IntPtr.Zero);
    }
    private Window Overlay(NativeRect rect, bool passthrough)
    {
        var window = new Window { WindowStyle = WindowStyle.None, ResizeMode = ResizeMode.NoResize,
            AllowsTransparency = true, Background = Brushes.Transparent, ShowInTaskbar = false,
            ShowActivated = false, Topmost = true, Width = 420, Height = 40 };
        window.SourceInitialized += (_, _) => {
            var handle = new WindowInteropHelper(window).Handle;
            var style = GetWindowLongPtr(handle, -20).ToInt64() | 0x08000000 | 0x80;
            if (passthrough) style |= 0x20; // Layered transparent window: mouse input passes through.
            SetWindowLongPtr(handle, -20, new IntPtr(style));
            SetWindowPos(handle, new IntPtr(-1), rect.Left, rect.Top, rect.Right - rect.Left,
                rect.Bottom - rect.Top, 0x0010 | 0x0200);
        };
        windows.Add(window);
        return window;
    }
    private void ShowDisplay(NativeRect rect)
    {
        var edge = Overlay(rect, true);
        var glow = new Grid { IsHitTestVisible = false, ClipToBounds = true };
        var transparent = Color.FromArgb(0, accent.R, accent.G, accent.B);
        var tinted = Color.FromArgb(118, accent.R, accent.G, accent.B);
        glow.Children.Add(new Border { Height = 72, VerticalAlignment = VerticalAlignment.Top,
            Background = new LinearGradientBrush(tinted, transparent, 90) });
        glow.Children.Add(new Border { Height = 72, VerticalAlignment = VerticalAlignment.Bottom,
            Background = new LinearGradientBrush(transparent, tinted, 90) });
        glow.Children.Add(new Border { Width = 72, HorizontalAlignment = HorizontalAlignment.Left,
            Background = new LinearGradientBrush(tinted, transparent, 0) });
        glow.Children.Add(new Border { Width = 72, HorizontalAlignment = HorizontalAlignment.Right,
            Background = new LinearGradientBrush(transparent, tinted, 0) });
        glow.Children.Add(new Border { BorderThickness = new Thickness(3), CornerRadius = new CornerRadius(12),
            BorderBrush = new SolidColorBrush(accent), Margin = new Thickness(2),
            Effect = new DropShadowEffect { Color = accent, BlurRadius = 16, ShadowDepth = 0, Opacity = .8 } });
        edge.Content = glow; edge.Show();
        // Window dimensions are placed in native display pixels, including mixed-DPI layouts.
        var dpi = GetDpiForWindow(new WindowInteropHelper(edge).Handle) / 96.0;
        var width = (int)(420 * dpi); var height = (int)(38 * dpi);
        var x = rect.Left + (rect.Right - rect.Left - width) / 2;
        var y = rect.Top + (int)(48 * dpi);
        var controls = Overlay(new NativeRect { Left = x, Top = y, Right = x + width, Bottom = y + height }, false);
        controls.Title = active ? "Ambi computer-use controls" : "Ambi screen-frame preview";
        var row = new DockPanel { LastChildFill = true, Margin = new Thickness(10, 4, 6, 4) };
        var stop = new Button { Content = active ? "Stop task" : "Close preview", Padding = new Thickness(10, 2, 10, 2), Focusable = false };
        stop.Click += (_, _) => { if (active) Stop?.Invoke(); else SetPreview(false); };
        DockPanel.SetDock(stop, Dock.Right); row.Children.Add(stop);
        row.Children.Add(new TextBlock { Text = active ? "Ambi is working" : "Ambi screen-frame preview",
            Foreground = Brushes.Black, VerticalAlignment = VerticalAlignment.Center, FontSize = 12 });
        controls.Content = new Border { Background = new SolidColorBrush(accent), CornerRadius = new CornerRadius(9), Child = row };
        controls.Show();
    }
    public void Dispose()
    {
        disposed = true; watchdog.Stop(); SystemEvents.DisplaySettingsChanged -= DisplaysChanged; Reset();
    }
    [StructLayout(LayoutKind.Sequential)] private struct NativeRect { public int Left, Top, Right, Bottom; }
    private delegate bool MonitorCallback(IntPtr monitor, IntPtr hdc, ref NativeRect rect, IntPtr data);
    [DllImport("user32.dll")] private static extern bool EnumDisplayMonitors(IntPtr hdc, IntPtr clip, MonitorCallback callback, IntPtr data);
    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] private static extern IntPtr GetWindowLongPtr(IntPtr handle, int index);
    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")] private static extern IntPtr SetWindowLongPtr(IntPtr handle, int index, IntPtr value);
    [DllImport("user32.dll")] private static extern bool SetWindowPos(IntPtr handle, IntPtr after, int x, int y, int width, int height, uint flags);
    [DllImport("user32.dll")] private static extern uint GetDpiForWindow(IntPtr handle);
}
