using System.Reflection;
using Autodesk.Revit.UI;

namespace SAEngine.RevitLink;

public sealed class SAEngineApp : IExternalApplication
{
    public const string TabName = "SAEngine";
    public const string PanelName = "Structural Exchange";

    public Result OnStartup(UIControlledApplication application)
    {
        try
        {
            application.CreateRibbonTab(TabName);
        }
        catch
        {
            // Tab already exists in this Revit session.
        }

        var panel = application.GetRibbonPanels(TabName)
            .FirstOrDefault(p => string.Equals(p.Name, PanelName, StringComparison.Ordinal))
            ?? application.CreateRibbonPanel(TabName, PanelName);

        var assemblyPath = Assembly.GetExecutingAssembly().Location;

        var importData = new PushButtonData(
            "SAEngineImport",
            "Import from\nSAEngine",
            assemblyPath,
            typeof(ImportCommand).FullName!
        )
        {
            ToolTip = "Import levels, grids, structural members, slabs, foundations, and rebar from a SAEngine .exchange.json file.",
        };

        var exportData = new PushButtonData(
            "SAEngineExport",
            "Export to\nSAEngine",
            assemblyPath,
            typeof(ExportCommand).FullName!
        )
        {
            ToolTip = "Export the current Revit structural model back to a SAEngine .exchange.json file.",
        };

        panel.AddItem(importData);
        panel.AddItem(exportData);

        return Result.Succeeded;
    }

    public Result OnShutdown(UIControlledApplication application) => Result.Succeeded;
}
