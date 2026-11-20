using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Structure;
using Autodesk.Revit.UI;
using SAEngine.RevitLink.Core;

namespace SAEngine.RevitLink;

[Transaction(TransactionMode.ReadOnly)]
public sealed class ExportCommand : IExternalCommand
{
    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        var doc = commandData.Application.ActiveUIDocument?.Document;
        if (doc is null)
        {
            message = "No active Revit document.";
            return Result.Failed;
        }

        var defaultName = string.IsNullOrWhiteSpace(doc.Title) ? "model" : Path.GetFileNameWithoutExtension(doc.Title);
        var saveDialog = new FileSaveDialog("SAEngine Exchange Files (*.exchange.json)|*.exchange.json|JSON Files (*.json)|*.json")
        {
            Title = "Export to SAEngine",
            InitialFileName = $"{defaultName}.exchange.json",
        };
        if (saveDialog.Show() != ItemSelectionDialogResult.Confirmed)
        {
            return Result.Cancelled;
        }

        var outPath = ModelPathUtils.ConvertModelPathToUserVisiblePath(saveDialog.GetSelectedModelPath());
        if (!outPath.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
        {
            outPath += ".exchange.json";
        }

        try
        {
            var exchange = BuildDocument(doc);
            ExchangeJson.Write(outPath, exchange);

            TaskDialog.Show(
                "SAEngine Export Summary",
                $"Exported to: {Path.GetFileName(outPath)}\n\n" +
                $"Levels: {exchange.Levels.Count}\n" +
                $"Grids: {exchange.Grids.Count}\n" +
                $"Sections: {exchange.Sections.Count}\n" +
                $"Elements: {exchange.Elements.Count}"
            );
            return Result.Succeeded;
        }
        catch (Exception ex)
        {
            TaskDialog.Show("SAEngine Export Failed", ex.Message);
            return Result.Failed;
        }
    }

    private static ExchangeDocument BuildDocument(Document doc)
    {
        var levels = new FilteredElementCollector(doc)
            .OfClass(typeof(Level))
            .Cast<Level>()
            .OrderBy(l => l.Elevation)
            .ToList();

        var levelById = levels.ToDictionary(l => l.Id.Value);
        var exchangeLevels = levels.Select(l => new ExchangeLevel
        {
            Id = ParameterStorage.GetId(l),
            Name = l.Name,
            Elevation = UnitConverter.FeetToRoundedMm(l.Elevation),
            RevitId = l.UniqueId,
        }).ToList();

        var grids = new FilteredElementCollector(doc)
            .OfClass(typeof(Grid))
            .Cast<Grid>()
            .OrderBy(g => g.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();

        var exchangeGrids = new List<ExchangeGrid>();
        foreach (var g in grids)
        {
            if (g.Curve is not Line line)
            {
                continue;
            }
            var p0 = line.GetEndPoint(0);
            var p1 = line.GetEndPoint(1);
            var start = new List<double> { UnitConverter.FeetToRoundedMm(p0.X), UnitConverter.FeetToRoundedMm(p0.Y) };
            var end = new List<double> { UnitConverter.FeetToRoundedMm(p1.X), UnitConverter.FeetToRoundedMm(p1.Y) };
            var (axis, pos) = GridHelper.ClassifyGrid(start, end);
            exchangeGrids.Add(new ExchangeGrid
            {
                Id = ParameterStorage.GetId(g),
                Name = g.Name,
                Axis = axis,
                Position = axis is not null ? pos : null,
                Start = start,
                End = end,
                RevitId = g.UniqueId,
            });
        }

        var sectionsById = new Dictionary<string, ExchangeSection>(StringComparer.OrdinalIgnoreCase);
        var materialsById = new Dictionary<string, ExchangeMaterial>(StringComparer.OrdinalIgnoreCase);
        var exchangeElements = new List<ExchangeElement>();

        ExportColumnsAndFraming(doc, levelById, sectionsById, materialsById, exchangeElements);
        ExportWalls(doc, levelById, sectionsById, materialsById, exchangeElements);
        ExportSlabs(doc, levelById, sectionsById, materialsById, exchangeElements);
        ExportFootings(doc, levelById, sectionsById, materialsById, exchangeElements);

        return new ExchangeDocument
        {
            Schema = ExchangeSchema.SchemaId,
            Origin = new ExchangeOrigin
            {
                Application = "Revit",
                Version = doc.Application.VersionNumber,
                Written = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                Document = doc.Title,
            },
            Project = new ExchangeProject
            {
                Name = string.IsNullOrWhiteSpace(doc.Title) ? "Revit Model" : Path.GetFileNameWithoutExtension(doc.Title),
                Type = "building",
            },
            Units = new ExchangeUnits(),
            Scope = [.. ExchangeSchema.RevitExportScope],
            Levels = exchangeLevels,
            Grids = exchangeGrids,
            Materials = [.. materialsById.Values],
            Sections = [.. sectionsById.Values],
            Elements = exchangeElements,
            Rebar = [],
            Notes = [],
        };
    }

    private static void ExportColumnsAndFraming(
        Document doc,
        Dictionary<long, Level> levelById,
        Dictionary<string, ExchangeSection> sections,
        Dictionary<string, ExchangeMaterial> materials,
        List<ExchangeElement> outElements
    )
    {
        var instances = new FilteredElementCollector(doc)
            .OfClass(typeof(FamilyInstance))
            .Cast<FamilyInstance>()
            .Where(fi => fi.Category is not null && (
                fi.Category.BuiltInCategory == BuiltInCategory.OST_StructuralColumns ||
                fi.Category.BuiltInCategory == BuiltInCategory.OST_StructuralFraming))
            .ToList();

        foreach (var fi in instances)
        {
            var isColumn = fi.Category!.BuiltInCategory == BuiltInCategory.OST_StructuralColumns;
            var kind = isColumn
                ? "column"
                : (fi.StructuralType == StructuralType.Brace ? "brace" : "beam");

            var secId = RegisterSymbolSection(doc, fi.Symbol, kind, sections, materials);
            var saId = ParameterStorage.GetId(fi);

            if (isColumn)
            {
                var (bot, top, baseLevel, topLevel, rot) = ExtractColumnGeometry(fi, levelById);
                if (bot is null || top is null)
                {
                    continue;
                }
                outElements.Add(new ExchangeElement
                {
                    Id = saId,
                    Kind = "column",
                    Section = secId,
                    Name = fi.Symbol.Name,
                    RevitId = fi.UniqueId,
                    Curve = [ToMmList(bot), ToMmList(top)],
                    Rotation = UnitConverter.NormalizeDeg(rot),
                    BaseLevel = LevelKey(baseLevel),
                    TopLevel = LevelKey(topLevel),
                });
            }
            else
            {
                if (fi.Location is not LocationCurve lc)
                {
                    continue;
                }
                var p0 = lc.Curve.GetEndPoint(0);
                var p1 = lc.Curve.GetEndPoint(1);
                var lvl = (fi.LevelId != ElementId.InvalidElementId && levelById.TryGetValue(fi.LevelId.Value, out var byElemLevel) ? byElemLevel : null)
                    ?? TryGetLevel(fi, BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM, levelById)
                    ?? TryGetLevel(fi, BuiltInParameter.FAMILY_LEVEL_PARAM, levelById);
                outElements.Add(new ExchangeElement
                {
                    Id = saId,
                    Kind = kind,
                    Section = secId,
                    Name = fi.Symbol.Name,
                    RevitId = fi.UniqueId,
                    Curve = [ToMmList(p0), ToMmList(p1)],
                    Level = LevelKey(lvl),
                    Reference = kind == "beam" ? "top" : null,
                });
            }
        }
    }

    private static void ExportWalls(
        Document doc,
        Dictionary<long, Level> levelById,
        Dictionary<string, ExchangeSection> sections,
        Dictionary<string, ExchangeMaterial> materials,
        List<ExchangeElement> outElements
    )
    {
        var walls = new FilteredElementCollector(doc)
            .OfClass(typeof(Wall))
            .Cast<Wall>()
            .Where(w => w.get_Parameter(BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT)?.AsInteger() == 1)
            .ToList();

        foreach (var wall in walls)
        {
            if (wall.Location is not LocationCurve lc)
            {
                continue;
            }
            var baseLvl = TryGetLevel(wall, BuiltInParameter.WALL_BASE_CONSTRAINT, levelById);
            var topLvl = TryGetLevel(wall, BuiltInParameter.WALL_HEIGHT_TYPE, levelById);
            var baseOffset = wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)?.AsDouble() ?? 0.0;
            var botZ = (baseLvl?.Elevation ?? 0.0) + baseOffset;
            var height = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)?.AsDouble()
                ?? ((topLvl?.Elevation ?? botZ + UnitConverter.MmToFeet(3000.0)) - botZ);
            var topZ = botZ + height;

            var p0 = lc.Curve.GetEndPoint(0);
            var p1 = lc.Curve.GetEndPoint(1);
            var secId = RegisterWallSection(doc, wall.WallType, sections, materials);

            outElements.Add(new ExchangeElement
            {
                Id = ParameterStorage.GetId(wall),
                Kind = "wall",
                Section = secId,
                Name = wall.WallType.Name,
                RevitId = wall.UniqueId,
                Curve =
                [
                    ToMmList(new XYZ(p0.X, p0.Y, botZ)),
                    ToMmList(new XYZ(p1.X, p1.Y, botZ)),
                ],
                Bottom = UnitConverter.FeetToRoundedMm(botZ),
                Top = UnitConverter.FeetToRoundedMm(topZ),
                BaseLevel = LevelKey(baseLvl),
                TopLevel = LevelKey(topLvl),
            });
        }
    }

    private static void ExportSlabs(
        Document doc,
        Dictionary<long, Level> levelById,
        Dictionary<string, ExchangeSection> sections,
        Dictionary<string, ExchangeMaterial> materials,
        List<ExchangeElement> outElements
    )
    {
        var floors = new FilteredElementCollector(doc)
            .OfClass(typeof(Floor))
            .Cast<Floor>()
            .Where(f => f.get_Parameter(BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL)?.AsInteger() == 1)
            .ToList();

        foreach (var floor in floors)
        {
            var lvl = TryGetLevel(floor, BuiltInParameter.LEVEL_PARAM, levelById);
            var offset = floor.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)?.AsDouble() ?? 0.0;
            var z = (lvl?.Elevation ?? 0.0) + offset;

            var (outer, openings) = ExtractFloorLoops(doc, floor, z);
            if (outer is null || outer.Count < 3)
            {
                continue;
            }

            var secId = RegisterFloorSection(doc, floor.FloorType, sections, materials);
            outElements.Add(new ExchangeElement
            {
                Id = ParameterStorage.GetId(floor),
                Kind = "slab",
                Section = secId,
                Name = floor.FloorType.Name,
                RevitId = floor.UniqueId,
                Outline = outer,
                Openings = openings.Count > 0 ? openings : null,
                Level = LevelKey(lvl),
                Reference = "top",
            });
        }
    }

    private static void ExportFootings(
        Document doc,
        Dictionary<long, Level> levelById,
        Dictionary<string, ExchangeSection> sections,
        Dictionary<string, ExchangeMaterial> materials,
        List<ExchangeElement> outElements
    )
    {
        var footings = new FilteredElementCollector(doc)
            .OfClass(typeof(FamilyInstance))
            .OfCategory(BuiltInCategory.OST_StructuralFoundation)
            .Cast<FamilyInstance>()
            .ToList();

        foreach (var ft in footings)
        {
            if (ft.Location is not LocationPoint lp)
            {
                continue;
            }
            var lvl = TryGetLevel(ft, BuiltInParameter.FAMILY_LEVEL_PARAM, levelById)
                ?? TryGetLevel(ft, BuiltInParameter.LEVEL_PARAM, levelById);
            var secId = RegisterSymbolSection(doc, ft.Symbol, "footing", sections, materials);
            outElements.Add(new ExchangeElement
            {
                Id = ParameterStorage.GetId(ft),
                Kind = "footing",
                Section = secId,
                Name = ft.Symbol.Name,
                RevitId = ft.UniqueId,
                Point = ToMmList(lp.Point),
                Rotation = UnitConverter.NormalizeDeg(UnitConverter.RadToDeg(lp.Rotation)),
                Level = LevelKey(lvl),
                Reference = "top",
            });
        }
    }

    private static (XYZ? Bot, XYZ? Top, Level? BaseLevel, Level? TopLevel, double RotationDeg)
        ExtractColumnGeometry(FamilyInstance col, Dictionary<long, Level> levelById)
    {
        var baseLvl = TryGetLevel(col, BuiltInParameter.FAMILY_BASE_LEVEL_PARAM, levelById);
        var topLvl = TryGetLevel(col, BuiltInParameter.FAMILY_TOP_LEVEL_PARAM, levelById);

        if (col.Location is LocationCurve lc)
        {
            var a = lc.Curve.GetEndPoint(0);
            var b = lc.Curve.GetEndPoint(1);
            return a.Z <= b.Z ? (a, b, baseLvl, topLvl, 0.0) : (b, a, baseLvl, topLvl, 0.0);
        }

        if (col.Location is LocationPoint lp)
        {
            var baseOff = col.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM)?.AsDouble() ?? 0.0;
            var topOff = col.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM)?.AsDouble() ?? 0.0;
            var botZ = baseLvl is not null ? baseLvl.Elevation + baseOff : lp.Point.Z;
            var topZ = topLvl is not null ? topLvl.Elevation + topOff : botZ + UnitConverter.MmToFeet(3000.0);
            var bot = new XYZ(lp.Point.X, lp.Point.Y, botZ);
            var top = new XYZ(lp.Point.X, lp.Point.Y, topZ);
            return (bot, top, baseLvl, topLvl, UnitConverter.RadToDeg(lp.Rotation));
        }

        return (null, null, null, null, 0.0);
    }

    private static (List<List<double>>? Outer, List<List<List<double>>> Openings) ExtractFloorLoops(
        Document doc,
        Floor floor,
        double zFeet
    )
    {
        var openings = new List<List<List<double>>>();
        List<List<double>>? outer = null;

        try
        {
            if (floor.SketchId != ElementId.InvalidElementId && doc.GetElement(floor.SketchId) is Sketch sketch)
            {
                var loops = new List<(double Area, List<List<double>> Points)>();
                foreach (CurveArray arr in sketch.Profile)
                {
                    var pts = new List<List<double>>();
                    foreach (Curve c in arr)
                    {
                        var p = c.GetEndPoint(0);
                        pts.Add(
                        [
                            UnitConverter.FeetToRoundedMm(p.X),
                            UnitConverter.FeetToRoundedMm(p.Y),
                            UnitConverter.FeetToRoundedMm(zFeet),
                        ]);
                    }
                    if (pts.Count >= 3)
                    {
                        loops.Add((PolygonArea(pts), pts));
                    }
                }

                if (loops.Count > 0)
                {
                    loops.Sort((a, b) => b.Area.CompareTo(a.Area));
                    outer = loops[0].Points;
                    for (var i = 1; i < loops.Count; i++)
                    {
                        openings.Add(loops[i].Points);
                    }
                }
            }
        }
        catch
        {
            // Fall back to bounding box if sketch profile cannot be read.
        }

        if (outer is null)
        {
            var bb = floor.get_BoundingBox(null);
            if (bb is not null)
            {
                var zMm = UnitConverter.FeetToRoundedMm(zFeet);
                outer =
                [
                    [UnitConverter.FeetToRoundedMm(bb.Min.X), UnitConverter.FeetToRoundedMm(bb.Min.Y), zMm],
                    [UnitConverter.FeetToRoundedMm(bb.Max.X), UnitConverter.FeetToRoundedMm(bb.Min.Y), zMm],
                    [UnitConverter.FeetToRoundedMm(bb.Max.X), UnitConverter.FeetToRoundedMm(bb.Max.Y), zMm],
                    [UnitConverter.FeetToRoundedMm(bb.Min.X), UnitConverter.FeetToRoundedMm(bb.Max.Y), zMm],
                ];
            }
        }

        return (outer, openings);
    }

    private static string RegisterSymbolSection(
        Document doc,
        FamilySymbol symbol,
        string kind,
        Dictionary<string, ExchangeSection> sections,
        Dictionary<string, ExchangeMaterial> materials
    )
    {
        var secId = symbol.Name;
        if (sections.ContainsKey(secId))
        {
            return secId;
        }

        var matId = RegisterMaterialFromElement(doc, symbol, materials);
        var section = new ExchangeSection
        {
            Id = secId,
            Name = symbol.Name,
            Kind = kind == "brace" ? "beam" : kind,
            Material = matId,
        };

        var b = ReadMm(symbol, "b", "Width", "bf", "Overall Width");
        var h = ReadMm(symbol, "h", "Height", "d", "Overall Depth", "Depth");
        var dia = ReadMm(symbol, "Diameter", "D", "Dia");
        var len = ReadMm(symbol, "Length", "L");
        var thick = ReadMm(symbol, "Foundation Thickness", "Thickness", "t");

        if (kind == "footing")
        {
            section.Length = len ?? b;
            section.Width = b ?? h;
            section.Thickness = thick ?? h;
        }
        else if (dia is > 0)
        {
            section.Profile = new ExchangeProfile { Shape = "circle", Radius = Math.Round(dia.Value / 2.0, 1) };
        }
        else if (b is > 0 && h is > 0)
        {
            section.Profile = new ExchangeProfile { Shape = "rectangle", XDim = b, YDim = h };
        }

        sections[secId] = section;
        return secId;
    }

    private static string RegisterWallSection(
        Document doc,
        WallType wallType,
        Dictionary<string, ExchangeSection> sections,
        Dictionary<string, ExchangeMaterial> materials
    )
    {
        var secId = wallType.Name;
        if (!sections.ContainsKey(secId))
        {
            sections[secId] = new ExchangeSection
            {
                Id = secId,
                Name = wallType.Name,
                Kind = "wall",
                Material = RegisterMaterialFromCompound(doc, wallType, materials),
                Thickness = UnitConverter.FeetToRoundedMm(wallType.Width),
                Structural = true,
            };
        }
        return secId;
    }

    private static string RegisterFloorSection(
        Document doc,
        FloorType floorType,
        Dictionary<string, ExchangeSection> sections,
        Dictionary<string, ExchangeMaterial> materials
    )
    {
        var secId = floorType.Name;
        if (!sections.ContainsKey(secId))
        {
            double? thicknessMm = null;
            try
            {
                var cs = floorType.GetCompoundStructure();
                if (cs is not null)
                {
                    thicknessMm = UnitConverter.FeetToRoundedMm(cs.GetWidth());
                }
            }
            catch
            {
                // Ignore non-compound floor types.
            }

            sections[secId] = new ExchangeSection
            {
                Id = secId,
                Name = floorType.Name,
                Kind = "slab",
                Material = RegisterMaterialFromCompound(doc, floorType, materials),
                Thickness = thicknessMm,
            };
        }
        return secId;
    }

    private static string? RegisterMaterialFromElement(
        Document doc,
        Element elem,
        Dictionary<string, ExchangeMaterial> materials
    )
    {
        var p = elem.get_Parameter(BuiltInParameter.STRUCTURAL_MATERIAL_PARAM)
            ?? elem.LookupParameter("Structural Material")
            ?? elem.LookupParameter("Material");
        if (p is not null && p.StorageType == StorageType.ElementId && p.AsElementId() != ElementId.InvalidElementId)
        {
            if (doc.GetElement(p.AsElementId()) is Material mat)
            {
                RegisterMaterial(mat, materials);
                return mat.Name;
            }
        }
        return null;
    }

    private static string? RegisterMaterialFromCompound(
        Document doc,
        HostObjAttributes hostType,
        Dictionary<string, ExchangeMaterial> materials
    )
    {
        try
        {
            var cs = hostType.GetCompoundStructure();
            if (cs is not null && cs.LayerCount > 0)
            {
                var coreIdx = cs.GetFirstCoreLayerIndex();
                var matId = cs.GetMaterialId(coreIdx >= 0 ? coreIdx : 0);
                if (matId != ElementId.InvalidElementId && doc.GetElement(matId) is Material mat)
                {
                    RegisterMaterial(mat, materials);
                    return mat.Name;
                }
            }
        }
        catch
        {
            // Ignore compound read failure.
        }
        return null;
    }

    private static void RegisterMaterial(Material mat, Dictionary<string, ExchangeMaterial> materials)
    {
        if (materials.ContainsKey(mat.Name))
        {
            return;
        }
        var category = mat.MaterialClass.Contains("Steel", StringComparison.OrdinalIgnoreCase)
            || mat.MaterialClass.Contains("Metal", StringComparison.OrdinalIgnoreCase)
            ? "steel"
            : "concrete";
        materials[mat.Name] = new ExchangeMaterial
        {
            Id = mat.Name,
            Name = mat.Name,
            Category = category,
        };
    }

    private static Level? TryGetLevel(Element elem, BuiltInParameter bip, Dictionary<long, Level> levelById)
    {
        var p = elem.get_Parameter(bip);
        if (p is not null && p.StorageType == StorageType.ElementId)
        {
            var id = p.AsElementId();
            if (id != ElementId.InvalidElementId && levelById.TryGetValue(id.Value, out var lvl))
            {
                return lvl;
            }
        }
        return null;
    }

    private static string? LevelKey(Level? level) => level is null ? null : (ParameterStorage.GetId(level) ?? level.Name);

    private static List<double> ToMmList(XYZ pt) =>
    [
        UnitConverter.FeetToRoundedMm(pt.X),
        UnitConverter.FeetToRoundedMm(pt.Y),
        UnitConverter.FeetToRoundedMm(pt.Z),
    ];

    private static double? ReadMm(Element elem, params string[] names)
    {
        foreach (var name in names)
        {
            var p = elem.LookupParameter(name);
            if (p is not null && p.HasValue && p.StorageType == StorageType.Double)
            {
                return UnitConverter.FeetToRoundedMm(p.AsDouble());
            }
        }
        return null;
    }

    private static double PolygonArea(List<List<double>> pts)
    {
        double sum = 0;
        for (var i = 0; i < pts.Count; i++)
        {
            var a = pts[i];
            var b = pts[(i + 1) % pts.Count];
            sum += a[0] * b[1] - b[0] * a[1];
        }
        return Math.Abs(sum) / 2.0;
    }
}
