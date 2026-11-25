using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Structure;
using Autodesk.Revit.UI;
using SAEngine.RevitLink.Core;

namespace SAEngine.RevitLink;

[Transaction(TransactionMode.Manual)]
public sealed class ImportCommand : IExternalCommand
{
    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        var uiDoc = commandData.Application.ActiveUIDocument;
        var doc = uiDoc?.Document;
        if (doc is null)
        {
            message = "No active Revit document.";
            return Result.Failed;
        }

        var openDialog = new FileOpenDialog("SAEngine Exchange Files (*.exchange.json)|*.exchange.json|JSON Files (*.json)|*.json")
        {
            Title = "Import from SAEngine",
        };
        if (openDialog.Show() != ItemSelectionDialogResult.Confirmed)
        {
            return Result.Cancelled;
        }

        var path = ModelPathUtils.ConvertModelPathToUserVisiblePath(openDialog.GetSelectedModelPath());
        ExchangeDocument exchange;
        try
        {
            exchange = ExchangeJson.Read(path);
        }
        catch (Exception ex)
        {
            TaskDialog.Show("SAEngine Import Error", $"Could not read exchange file:\n{ex.Message}");
            return Result.Failed;
        }

        var summary = new ImportExportSummary();
        var failureHandler = new FailureHandler();

        using var tx = new Transaction(doc, "Import from SAEngine");
        var failureOpts = tx.GetFailureHandlingOptions();
        failureOpts.SetFailuresPreprocessor(failureHandler);
        tx.SetFailureHandlingOptions(failureOpts);

        try
        {
            tx.Start();

            ParameterStorage.EnsureParameter(doc);

            var levelMap = SyncLevels(doc, exchange.Levels, summary);
            SyncGrids(doc, exchange.Grids, exchange.Elements, summary);

            var typeResolver = new RevitTypeResolver(doc, summary);
            typeResolver.EnsureMaterials(exchange.Materials);
            typeResolver.TryLoadDefaultFamilies(exchange.Elements.Select(e => e.Kind));

            var (symbols, wallTypes, floorTypes) = ResolveSections(exchange, typeResolver, summary);

            doc.Regenerate();

            var elementMap = SyncElements(
                doc, exchange, levelMap, symbols, wallTypes, floorTypes, summary
            );

            doc.Regenerate();

            SyncRebar(doc, exchange.Rebar, elementMap, typeResolver, summary);

            tx.Commit();
        }
        catch (Exception ex)
        {
            if (tx.HasStarted())
            {
                tx.RollBack();
            }
            TaskDialog.Show("SAEngine Import Failed", ex.Message);
            return Result.Failed;
        }

        foreach (var msg in failureHandler.Messages.Distinct())
        {
            summary.Warnings.Add(msg);
        }

        TaskDialog.Show("SAEngine Import Summary", summary.FormatImportReport(Path.GetFileName(path)));
        return Result.Succeeded;
    }

    private static Dictionary<string, Level> SyncLevels(
        Document doc,
        List<ExchangeLevel> incoming,
        ImportExportSummary summary
    )
    {
        var existing = new FilteredElementCollector(doc)
            .OfClass(typeof(Level))
            .Cast<Level>()
            .ToList();

        var result = new Dictionary<string, Level>(StringComparer.OrdinalIgnoreCase);

        foreach (var src in incoming)
        {
            var level = FindElement(doc, existing, src.Id, src.RevitId)
                ?? existing.FirstOrDefault(l => string.Equals(l.Name, src.Name, StringComparison.OrdinalIgnoreCase));

            var targetElevFeet = UnitConverter.MmToFeet(src.Elevation);
            if (level is null)
            {
                level = Level.Create(doc, targetElevFeet);
                if (!string.IsNullOrWhiteSpace(src.Name))
                {
                    TryRename(level, src.Name);
                }
                existing.Add(level);
                summary.LevelsCreated++;
            }
            else
            {
                var curMm = UnitConverter.FeetToMm(level.Elevation);
                if (Math.Abs(curMm - src.Elevation) > UnitConverter.PositionToleranceMm)
                {
                    level.Elevation = targetElevFeet;
                    summary.LevelsUpdated++;
                }
            }

            ParameterStorage.SetId(level, src.Id);
            if (!string.IsNullOrWhiteSpace(src.Id))
            {
                result[src.Id] = level;
            }
            if (!string.IsNullOrWhiteSpace(src.Name))
            {
                result[src.Name] = level;
            }
        }

        return result;
    }

    private static void SyncGrids(
        Document doc,
        List<ExchangeGrid> incoming,
        List<ExchangeElement> elems,
        ImportExportSummary summary
    )
    {
        if (incoming.Count == 0)
        {
            return;
        }

        var (minX, maxX, minY, maxY) = ComputePlanExtentsMm(incoming, elems);
        var existing = new FilteredElementCollector(doc)
            .OfClass(typeof(Grid))
            .Cast<Grid>()
            .ToList();

        foreach (var src in incoming)
        {
            var pts = GridHelper.ResolveEndpointsMm(src, minX, maxX, minY, maxY);
            if (pts is null)
            {
                summary.Warnings.Add($"Grid '{src.Name}' skipped: missing endpoints.");
                continue;
            }

            var p0 = new XYZ(UnitConverter.MmToFeet(pts.Value.Start.X), UnitConverter.MmToFeet(pts.Value.Start.Y), 0.0);
            var p1 = new XYZ(UnitConverter.MmToFeet(pts.Value.End.X), UnitConverter.MmToFeet(pts.Value.End.Y), 0.0);

            var grid = FindElement(doc, existing, src.Id, src.RevitId)
                ?? existing.FirstOrDefault(g => string.Equals(g.Name, src.Name, StringComparison.OrdinalIgnoreCase));

            if (grid is null)
            {
                var line = Line.CreateBound(p0, p1);
                grid = Grid.Create(doc, line);
                if (!string.IsNullOrWhiteSpace(src.Name))
                {
                    TryRename(grid, src.Name);
                }
                existing.Add(grid);
                summary.GridsCreated++;
            }
            else if (grid.Curve is Line existingLine)
            {
                var curStart = existingLine.GetEndPoint(0);
                var curEnd = existingLine.GetEndPoint(1);
                var delta = new XYZ(p0.X - curStart.X, p0.Y - curStart.Y, 0.0);
                var dirSame = existingLine.Direction.CrossProduct((p1 - p0).Normalize()).GetLength() < 1e-4;
                if (dirSame && delta.GetLength() > UnitConverter.MmToFeet(UnitConverter.PositionToleranceMm))
                {
                    ElementTransformUtils.MoveElement(doc, grid.Id, delta);
                    summary.GridsUpdated++;
                }
                else if (!dirSame)
                {
                    summary.Warnings.Add($"Grid '{src.Name}' changed angle in exchange file and was kept at its existing Revit orientation.");
                }
                else if (curStart.DistanceTo(p0) > UnitConverter.MmToFeet(UnitConverter.PositionToleranceMm)
                    && curEnd.DistanceTo(p1) > UnitConverter.MmToFeet(UnitConverter.PositionToleranceMm))
                {
                    ElementTransformUtils.MoveElement(doc, grid.Id, delta);
                    summary.GridsUpdated++;
                }
            }

            ParameterStorage.SetId(grid, src.Id);
        }
    }

    private static (
        Dictionary<string, FamilySymbol> Symbols,
        Dictionary<string, WallType> WallTypes,
        Dictionary<string, FloorType> FloorTypes
    ) ResolveSections(
        ExchangeDocument exchange,
        RevitTypeResolver resolver,
        ImportExportSummary summary
    )
    {
        var symbols = new Dictionary<string, FamilySymbol>(StringComparer.OrdinalIgnoreCase);
        var wallTypes = new Dictionary<string, WallType>(StringComparer.OrdinalIgnoreCase);
        var floorTypes = new Dictionary<string, FloorType>(StringComparer.OrdinalIgnoreCase);

        var kindsBySection = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var e in exchange.Elements)
        {
            if (!string.IsNullOrWhiteSpace(e.Section) && !kindsBySection.ContainsKey(e.Section))
            {
                kindsBySection[e.Section] = e.Kind;
            }
        }

        foreach (var sec in exchange.Sections)
        {
            var kind = !string.IsNullOrWhiteSpace(sec.Kind)
                ? sec.Kind
                : kindsBySection.GetValueOrDefault(sec.Id, "");

            switch (kind)
            {
                case "wall":
                {
                    var wt = resolver.ResolveWallType(sec);
                    if (wt is not null)
                    {
                        wallTypes[sec.Id] = wt;
                    }
                    else
                    {
                        summary.UnmatchedSections.Add($"{sec.Name} ({sec.Id}, wall)");
                    }
                    break;
                }
                case "slab" or "area":
                {
                    var ft = resolver.ResolveFloorType(sec);
                    if (ft is not null)
                    {
                        floorTypes[sec.Id] = ft;
                    }
                    else
                    {
                        summary.UnmatchedSections.Add($"{sec.Name} ({sec.Id}, slab)");
                    }
                    break;
                }
                case "column" or "beam" or "brace" or "member" or "footing" or "pileCap":
                {
                    var mappedKind = kind == "pileCap" ? "footing" : kind;
                    var sym = resolver.ResolveFamilySymbol(sec, mappedKind);
                    if (sym is not null)
                    {
                        symbols[sec.Id] = sym;
                    }
                    else
                    {
                        summary.UnmatchedSections.Add($"{sec.Name} ({sec.Id}, {kind})");
                    }
                    break;
                }
            }
        }

        return (symbols, wallTypes, floorTypes);
    }

    private static Dictionary<string, Element> SyncElements(
        Document doc,
        ExchangeDocument exchange,
        Dictionary<string, Level> levelMap,
        Dictionary<string, FamilySymbol> symbols,
        Dictionary<string, WallType> wallTypes,
        Dictionary<string, FloorType> floorTypes,
        ImportExportSummary summary
    )
    {
        var bySaengineId = new Dictionary<string, Element>(StringComparer.OrdinalIgnoreCase);
        var existing = new FilteredElementCollector(doc)
            .WhereElementIsNotElementType()
            .Where(e => e.Category is not null && (
                e.Category.BuiltInCategory == BuiltInCategory.OST_StructuralColumns ||
                e.Category.BuiltInCategory == BuiltInCategory.OST_StructuralFraming ||
                e.Category.BuiltInCategory == BuiltInCategory.OST_Walls ||
                e.Category.BuiltInCategory == BuiltInCategory.OST_Floors ||
                e.Category.BuiltInCategory == BuiltInCategory.OST_StructuralFoundation))
            .ToList();

        foreach (var e in existing)
        {
            var sid = ParameterStorage.GetId(e);
            if (!string.IsNullOrWhiteSpace(sid))
            {
                bySaengineId[sid] = e;
            }
        }

        var allLevels = levelMap.Values.DistinctBy(l => l.Id.Value).OrderBy(l => l.Elevation).ToList();
        var hostMap = new Dictionary<string, Element>(StringComparer.OrdinalIgnoreCase);

        foreach (var src in exchange.Elements)
        {
            Element? current = null;
            if (!string.IsNullOrWhiteSpace(src.Id) && bySaengineId.TryGetValue(src.Id, out var foundByParam))
            {
                current = foundByParam;
            }
            else if (!string.IsNullOrWhiteSpace(src.RevitId))
            {
                current = doc.GetElement(src.RevitId);
            }

            try
            {
                Element? saved = src.Kind switch
                {
                    "column" => UpsertColumn(doc, src, current, symbols, levelMap, allLevels, summary),
                    "beam" or "brace" or "member" => UpsertFraming(doc, src, current, symbols, levelMap, allLevels, summary),
                    "wall" => UpsertWall(doc, src, current, wallTypes, levelMap, allLevels, summary),
                    "slab" or "area" => UpsertSlab(doc, src, current, floorTypes, levelMap, allLevels, summary),
                    "footing" => UpsertFooting(doc, src, current, symbols, levelMap, allLevels, summary),
                    _ => null,
                };

                if (saved is not null)
                {
                    ParameterStorage.SetId(saved, src.Id);
                    if (!string.IsNullOrWhiteSpace(src.Id))
                    {
                        hostMap[src.Id] = saved;
                    }
                }
                else
                {
                    summary.ElementsSkipped++;
                }
            }
            catch (Exception ex)
            {
                summary.ElementsSkipped++;
                summary.Warnings.Add($"{src.Kind} '{src.Id ?? src.RevitId ?? "?"}': {ex.Message}");
            }
        }

        return hostMap;
    }

    private static Element? UpsertColumn(
        Document doc,
        ExchangeElement src,
        Element? existing,
        Dictionary<string, FamilySymbol> symbols,
        Dictionary<string, Level> levelMap,
        List<Level> allLevels,
        ImportExportSummary summary
    )
    {
        if (src.Curve is not { Count: 2 } || src.Section is null || !symbols.TryGetValue(src.Section, out var symbol))
        {
            return null;
        }

        var p0 = ToXyz(src.Curve[0]);
        var p1 = ToXyz(src.Curve[1]);
        var basePt = p0.Z <= p1.Z ? p0 : p1;
        var topPt = p0.Z <= p1.Z ? p1 : p0;
        var baseLevel = FindLevel(levelMap, allLevels, src.BaseLevel, basePt.Z);
        var topLevel = FindLevel(levelMap, allLevels, src.TopLevel, topPt.Z);
        if (baseLevel is null)
        {
            return null;
        }

        var isSlanted = Math.Abs(basePt.X - topPt.X) > 1e-4 || Math.Abs(basePt.Y - topPt.Y) > 1e-4;
        FamilyInstance? col = existing as FamilyInstance;
        if (col is not null && !isSlanted)
        {
            if (col.Symbol.Id != symbol.Id)
            {
                col.Symbol = symbol;
            }
            if (col.Location is LocationPoint lp)
            {
                var target = new XYZ(basePt.X, basePt.Y, lp.Point.Z);
                if (lp.Point.DistanceTo(target) > UnitConverter.MmToFeet(UnitConverter.PositionToleranceMm))
                {
                    ElementTransformUtils.MoveElement(doc, col.Id, target - lp.Point);
                }
                ApplyRotation(doc, col, basePt, src.Rotation ?? 0.0, lp.Rotation);
            }
            SetColumnLevels(col, baseLevel, topLevel, basePt.Z, topPt.Z);
            summary.ElementsUpdated++;
            return col;
        }

        if (existing is not null)
        {
            doc.Delete(existing.Id);
        }

        col = isSlanted
            ? doc.Create.NewFamilyInstance(Line.CreateBound(basePt, topPt), symbol, baseLevel, StructuralType.Column)
            : doc.Create.NewFamilyInstance(basePt, symbol, baseLevel, StructuralType.Column);

        if (!isSlanted)
        {
            SetColumnLevels(col, baseLevel, topLevel, basePt.Z, topPt.Z);
            if (src.Rotation is not null && Math.Abs(src.Rotation.Value) > 1e-3)
            {
                ApplyRotation(doc, col, basePt, src.Rotation.Value, 0.0);
            }
        }

        summary.ElementsCreated++;
        return col;
    }

    private static void SetColumnLevels(FamilyInstance col, Level baseLevel, Level? topLevel, double baseZ, double topZ)
    {
        col.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM)?.Set(baseLevel.Id);
        col.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM)?.Set(baseZ - baseLevel.Elevation);
        if (topLevel is not null)
        {
            col.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM)?.Set(topLevel.Id);
            col.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM)?.Set(topZ - topLevel.Elevation);
        }
    }

    private static Element? UpsertFraming(
        Document doc,
        ExchangeElement src,
        Element? existing,
        Dictionary<string, FamilySymbol> symbols,
        Dictionary<string, Level> levelMap,
        List<Level> allLevels,
        ImportExportSummary summary
    )
    {
        if (src.Curve is not { Count: 2 } || src.Section is null || !symbols.TryGetValue(src.Section, out var symbol))
        {
            return null;
        }

        var p0 = ToXyz(src.Curve[0]);
        var p1 = ToXyz(src.Curve[1]);
        if (p0.DistanceTo(p1) < UnitConverter.MmToFeet(UnitConverter.ShortCurveToleranceMm))
        {
            return null;
        }

        var level = FindLevel(levelMap, allLevels, src.Level, (p0.Z + p1.Z) / 2.0);
        if (level is null)
        {
            return null;
        }

        var st = src.Kind == "brace" ? StructuralType.Brace : StructuralType.Beam;
        var line = Line.CreateBound(p0, p1);
        if (existing is FamilyInstance fi)
        {
            if (fi.Symbol.Id != symbol.Id)
            {
                fi.Symbol = symbol;
            }
            if (fi.Location is LocationCurve lc)
            {
                lc.Curve = line;
            }
            summary.ElementsUpdated++;
            return fi;
        }

        var created = doc.Create.NewFamilyInstance(line, symbol, level, st);
        if (string.Equals(src.Reference, "top", StringComparison.OrdinalIgnoreCase))
        {
            var zJust = created.get_Parameter(BuiltInParameter.Z_JUSTIFICATION);
            if (zJust is not null && !zJust.IsReadOnly)
            {
                zJust.Set(0); // Top
            }
        }
        summary.ElementsCreated++;
        return created;
    }

    private static Element? UpsertWall(
        Document doc,
        ExchangeElement src,
        Element? existing,
        Dictionary<string, WallType> wallTypes,
        Dictionary<string, Level> levelMap,
        List<Level> allLevels,
        ImportExportSummary summary
    )
    {
        if (src.Curve is not { Count: 2 } || src.Section is null || !wallTypes.TryGetValue(src.Section, out var wallType))
        {
            return null;
        }

        var p0 = ToXyz(src.Curve[0]);
        var p1 = ToXyz(src.Curve[1]);
        var botZ = src.Bottom is not null ? UnitConverter.MmToFeet(src.Bottom.Value) : p0.Z;
        var topZ = src.Top is not null ? UnitConverter.MmToFeet(src.Top.Value) : botZ + UnitConverter.MmToFeet(3000.0);
        var height = Math.Max(topZ - botZ, UnitConverter.MmToFeet(100.0));

        var baseLevel = FindLevel(levelMap, allLevels, src.BaseLevel, botZ);
        var topLevel = FindLevel(levelMap, allLevels, src.TopLevel, topZ);
        if (baseLevel is null)
        {
            return null;
        }

        var line = Line.CreateBound(new XYZ(p0.X, p0.Y, baseLevel.Elevation), new XYZ(p1.X, p1.Y, baseLevel.Elevation));
        var baseOffset = botZ - baseLevel.Elevation;

        if (existing is Wall wall)
        {
            if (wall.WallType.Id != wallType.Id)
            {
                wall.WallType = wallType;
            }
            if (wall.Location is LocationCurve lc)
            {
                lc.Curve = line;
            }
            wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)?.Set(baseLevel.Id);
            wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)?.Set(baseOffset);
            if (topLevel is not null)
            {
                wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)?.Set(topLevel.Id);
                wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)?.Set(topZ - topLevel.Elevation);
            }
            else
            {
                wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)?.Set(height);
            }
            summary.ElementsUpdated++;
            return wall;
        }

        var created = Wall.Create(doc, line, wallType.Id, baseLevel.Id, height, baseOffset, false, true);
        if (topLevel is not null)
        {
            created.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)?.Set(topLevel.Id);
            created.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)?.Set(topZ - topLevel.Elevation);
        }
        summary.ElementsCreated++;
        return created;
    }

    private static Element? UpsertSlab(
        Document doc,
        ExchangeElement src,
        Element? existing,
        Dictionary<string, FloorType> floorTypes,
        Dictionary<string, Level> levelMap,
        List<Level> allLevels,
        ImportExportSummary summary
    )
    {
        if (src.Outline is not { Count: >= 3 } || src.Section is null || !floorTypes.TryGetValue(src.Section, out var floorType))
        {
            return null;
        }

        var z = UnitConverter.MmToFeet(src.Outline[0][2]);
        var level = FindLevel(levelMap, allLevels, src.Level, z);
        if (level is null)
        {
            return null;
        }

        var loops = new List<CurveLoop>();
        var outer = BuildCurveLoop(src.Outline, level.Elevation);
        if (outer is null)
        {
            return null;
        }
        loops.Add(outer);

        if (src.Openings is not null)
        {
            foreach (var hole in src.Openings)
            {
                var holeLoop = BuildCurveLoop(hole, level.Elevation);
                if (holeLoop is not null)
                {
                    loops.Add(holeLoop);
                }
            }
        }

        if (existing is not null)
        {
            doc.Delete(existing.Id);
            summary.ElementsUpdated++;
        }
        else
        {
            summary.ElementsCreated++;
        }

        var floor = Floor.Create(doc, loops, floorType.Id, level.Id);
        floor.get_Parameter(BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL)?.Set(1);
        var offset = z - level.Elevation;
        if (Math.Abs(offset) > 1e-4)
        {
            floor.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)?.Set(offset);
        }
        return floor;
    }

    private static Element? UpsertFooting(
        Document doc,
        ExchangeElement src,
        Element? existing,
        Dictionary<string, FamilySymbol> symbols,
        Dictionary<string, Level> levelMap,
        List<Level> allLevels,
        ImportExportSummary summary
    )
    {
        if (src.Point is not { Count: 3 } || src.Section is null || !symbols.TryGetValue(src.Section, out var symbol))
        {
            return null;
        }

        var pt = ToXyz(src.Point);
        var level = FindLevel(levelMap, allLevels, src.Level, pt.Z);
        if (level is null)
        {
            return null;
        }

        if (existing is FamilyInstance fi)
        {
            if (fi.Symbol.Id != symbol.Id)
            {
                fi.Symbol = symbol;
            }
            if (fi.Location is LocationPoint lp)
            {
                var delta = pt - lp.Point;
                if (delta.GetLength() > UnitConverter.MmToFeet(UnitConverter.PositionToleranceMm))
                {
                    ElementTransformUtils.MoveElement(doc, fi.Id, delta);
                }
                ApplyRotation(doc, fi, pt, src.Rotation ?? 0.0, lp.Rotation);
            }
            summary.ElementsUpdated++;
            return fi;
        }

        var created = doc.Create.NewFamilyInstance(pt, symbol, level, StructuralType.Footing);
        if (src.Rotation is not null && Math.Abs(src.Rotation.Value) > 1e-3)
        {
            ApplyRotation(doc, created, pt, src.Rotation.Value, 0.0);
        }
        summary.ElementsCreated++;
        return created;
    }

    private static void SyncRebar(
        Document doc,
        List<ExchangeRebar> rebarSets,
        Dictionary<string, Element> hostMap,
        RevitTypeResolver resolver,
        ImportExportSummary summary
    )
    {
        foreach (var barSet in rebarSets)
        {
            if (!hostMap.TryGetValue(barSet.Host, out var host))
            {
                summary.RebarSkipped++;
                summary.RebarNotes.Add($"{barSet.Id}: host '{barSet.Host}' not found in Revit model.");
                continue;
            }

            var hostData = RebarHostData.GetRebarHostData(host);
            if (hostData is null || !hostData.IsValidHost())
            {
                summary.RebarSkipped++;
                summary.RebarNotes.Add($"{barSet.Id}: element '{barSet.Host}' is not a valid Revit rebar host.");
                continue;
            }

            var barType = resolver.ResolveRebarBarType(barSet.Dia > 0 ? barSet.Dia : 16.0);
            if (barType is null)
            {
                summary.RebarSkipped++;
                summary.RebarNotes.Add($"{barSet.Id}: no RebarBarType loaded in template.");
                continue;
            }

            var style = barSet.Transverse ? RebarStyle.StirrupTie : RebarStyle.Standard;
            var placedAny = false;
            foreach (var polyline in barSet.Lines)
            {
                var curves = BuildCurves(polyline);
                if (curves.Count == 0)
                {
                    continue;
                }

                var normal = ComputeCurveNormal(curves);
                try
                {
                    using var terminations = new BarTerminationsData(doc)
                    {
                        TerminationOrientationAtStart = RebarTerminationOrientation.Left,
                        TerminationOrientationAtEnd = RebarTerminationOrientation.Left,
                    };
                    var rebar = Rebar.CreateFromCurves(
                        doc,
                        style,
                        barType,
                        host,
                        normal,
                        curves,
                        terminations,
                        true,
                        true
                    );
                    if (rebar is not null)
                    {
                        ParameterStorage.SetId(rebar, barSet.Id);
                        placedAny = true;
                        summary.RebarCreated++;
                    }
                }
                catch (Exception ex)
                {
                    summary.RebarSkipped++;
                    summary.RebarNotes.Add($"{barSet.Id} ({barSet.Mark}): {ex.Message}");
                }
            }

            if (!placedAny && barSet.Lines.Count == 0)
            {
                summary.RebarSkipped++;
            }
        }
    }

    private static List<Curve> BuildCurves(List<List<double>> polyline)
    {
        var curves = new List<Curve>();
        var minLen = UnitConverter.MmToFeet(UnitConverter.ShortCurveToleranceMm);
        for (var i = 0; i + 1 < polyline.Count; i++)
        {
            if (polyline[i].Count < 3 || polyline[i + 1].Count < 3)
            {
                continue;
            }
            var a = ToXyz(polyline[i]);
            var b = ToXyz(polyline[i + 1]);
            if (a.DistanceTo(b) >= minLen)
            {
                curves.Add(Line.CreateBound(a, b));
            }
        }
        return curves;
    }

    private static XYZ ComputeCurveNormal(List<Curve> curves)
    {
        if (curves.Count >= 2)
        {
            var d1 = (curves[0].GetEndPoint(1) - curves[0].GetEndPoint(0)).Normalize();
            for (var i = 1; i < curves.Count; i++)
            {
                var d2 = (curves[i].GetEndPoint(1) - curves[i].GetEndPoint(0)).Normalize();
                var cross = d1.CrossProduct(d2);
                if (cross.GetLength() > 1e-4)
                {
                    return cross.Normalize();
                }
            }
        }

        var dir = (curves[0].GetEndPoint(1) - curves[0].GetEndPoint(0)).Normalize();
        var fallback = Math.Abs(dir.Z) < 0.9 ? XYZ.BasisZ : XYZ.BasisX;
        return dir.CrossProduct(fallback).Normalize();
    }

    private static CurveLoop? BuildCurveLoop(List<List<double>> points, double elevationFeet)
    {
        var loop = new CurveLoop();
        var minLen = UnitConverter.MmToFeet(UnitConverter.ShortCurveToleranceMm);
        var xyzs = points.Select(p => new XYZ(UnitConverter.MmToFeet(p[0]), UnitConverter.MmToFeet(p[1]), elevationFeet)).ToList();
        var added = 0;
        for (var i = 0; i < xyzs.Count; i++)
        {
            var a = xyzs[i];
            var b = xyzs[(i + 1) % xyzs.Count];
            if (a.DistanceTo(b) >= minLen)
            {
                loop.Append(Line.CreateBound(a, b));
                added++;
            }
        }
        return added >= 3 ? loop : null;
    }

    private static void ApplyRotation(Document doc, Element elem, XYZ origin, double targetDeg, double currentRad)
    {
        var targetRad = UnitConverter.DegToRad(targetDeg);
        var delta = targetRad - currentRad;
        if (Math.Abs(UnitConverter.RadToDeg(delta)) <= UnitConverter.AngleToleranceDeg)
        {
            return;
        }
        var axis = Line.CreateBound(origin, origin + XYZ.BasisZ);
        ElementTransformUtils.RotateElement(doc, elem.Id, axis, delta);
    }

    private static Level? FindLevel(
        Dictionary<string, Level> levelMap,
        List<Level> allLevels,
        string? levelKey,
        double fallbackZFeet
    )
    {
        if (!string.IsNullOrWhiteSpace(levelKey) && levelMap.TryGetValue(levelKey, out var mapped))
        {
            return mapped;
        }
        return allLevels
            .OrderBy(l => Math.Abs(l.Elevation - fallbackZFeet))
            .FirstOrDefault();
    }

    private static T? FindElement<T>(Document doc, IEnumerable<T> pool, string? saengineId, string? revitId)
        where T : Element
    {
        if (!string.IsNullOrWhiteSpace(saengineId))
        {
            var byParam = pool.FirstOrDefault(e =>
                string.Equals(ParameterStorage.GetId(e), saengineId, StringComparison.OrdinalIgnoreCase));
            if (byParam is not null)
            {
                return byParam;
            }
        }

        if (!string.IsNullOrWhiteSpace(revitId) && doc.GetElement(revitId) is T byUid)
        {
            return byUid;
        }

        return null;
    }

    private static (double MinX, double MaxX, double MinY, double MaxY) ComputePlanExtentsMm(
        List<ExchangeGrid> grids,
        List<ExchangeElement> elems
    )
    {
        var xs = new List<double>();
        var ys = new List<double>();

        foreach (var g in grids)
        {
            if (g.Start is { Count: >= 2 } && g.End is { Count: >= 2 })
            {
                xs.Add(g.Start[0]);
                xs.Add(g.End[0]);
                ys.Add(g.Start[1]);
                ys.Add(g.End[1]);
            }
            else if (g.Position is not null)
            {
                if (string.Equals(g.Axis, "x", StringComparison.OrdinalIgnoreCase))
                {
                    xs.Add(g.Position.Value);
                }
                else if (string.Equals(g.Axis, "y", StringComparison.OrdinalIgnoreCase))
                {
                    ys.Add(g.Position.Value);
                }
            }
        }

        foreach (var e in elems)
        {
            if (e.Curve is not null)
            {
                foreach (var p in e.Curve)
                {
                    xs.Add(p[0]);
                    ys.Add(p[1]);
                }
            }
            if (e.Outline is not null)
            {
                foreach (var p in e.Outline)
                {
                    xs.Add(p[0]);
                    ys.Add(p[1]);
                }
            }
            if (e.Point is { Count: >= 2 })
            {
                xs.Add(e.Point[0]);
                ys.Add(e.Point[1]);
            }
        }

        return (
            xs.Count > 0 ? xs.Min() : 0.0,
            xs.Count > 0 ? xs.Max() : 10000.0,
            ys.Count > 0 ? ys.Min() : 0.0,
            ys.Count > 0 ? ys.Max() : 10000.0
        );
    }

    private static XYZ ToXyz(IReadOnlyList<double> ptMm) => new(
        UnitConverter.MmToFeet(ptMm[0]),
        UnitConverter.MmToFeet(ptMm[1]),
        ptMm.Count > 2 ? UnitConverter.MmToFeet(ptMm[2]) : 0.0
    );

    private static void TryRename(Element elem, string name)
    {
        try
        {
            elem.Name = name;
        }
        catch
        {
            // Ignore duplicate-name errors from Revit.
        }
    }
}
