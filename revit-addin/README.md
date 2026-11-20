# SAEngine Revit 2027 Add-in

An independent **MIT-licensed** Revit 2027 add-in (.NET 10) that completes the SAEngine Revit link (`saengine.structuralExchange/1`). It reads and writes `<project>.exchange.json` files without referencing or linking any AGPL code from SAEngine.

## Projects

- `SAEngine.RevitLink.Core` (`net8.0`): Pure C# DTOs, JSON serialization, unit conversions (mm/deg <-> feet/rad), grid classification, section matching, and summary reporting with no Revit API dependencies.
- `SAEngine.RevitLink` (`net10.0-windows`, the framework of Revit 2027's API): Revit 2027 `IExternalApplication` adding the **SAEngine** ribbon tab with **Import from SAEngine** and **Export to SAEngine** commands.
- `SAEngine.RevitLink.addin`: Revit 2027 add-in manifest.

## Build

Requires the .NET 10 SDK and Autodesk Revit 2027 installed (default `$(ProgramW6432)\Autodesk\Revit 2027`):

```powershell
dotnet build revit-addin -c Release
```

To override the Revit installation directory:

```powershell
dotnet build revit-addin -c Release -p:RevitInstallDir="D:\Autodesk\Revit 2027"
```

Note: `RevitAPI.dll` and `RevitAPIUI.dll` are referenced with `Private=false` so they are not copied to the build output.

## Install into Revit 2027

Copy the contents of `revit-addin\SAEngine.RevitLink\bin\Release\net10.0-windows\` (`SAEngine.RevitLink.dll`, `SAEngine.RevitLink.Core.dll`) and `revit-addin\SAEngine.RevitLink.addin` to:

```text
%ProgramData%\Autodesk\Revit\Addins\2027\
```

(Or `%AppData%\Autodesk\Revit\Addins\2027\` for the current user.)
