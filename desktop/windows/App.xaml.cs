using System.Windows;
namespace AmbiCompanion;
public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        MainWindow = new CompanionWindow();
        MainWindow.Show();
    }
}
