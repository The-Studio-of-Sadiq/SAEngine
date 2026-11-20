using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Structure;
using SAEngine.RevitLink.Core;

namespace SAEngine.RevitLink;

internal sealed class RevitTypeResolver
{
    private readonly Document _doc;
    private readonly ImportExportSummary _summary;
    private readonly Dictionary<string, Material> _materials = new(StringComparer.OrdinalIgnoreCase);

    private static readonly Dictionary<string, string[]> DefaultFamilyNames = new(StringComparer.OrdinalIgnoreCase)
    {
        ["column"] =
        [
            "M_Concrete-Rectangular-Column",
            "Concrete-Rectangular-Column",
            "M_Concrete-Round-Column",
            "Concrete-Round-Column",
            "M_W-Wide Flange-Column",
            "W-Wide Flange-Column",
        ],
        ["beam"] =
        [
            "M_Concrete-Rectangular Beam",
            "Concrete-Rectangular Beam",
            "M_W-Wide Flange",
            "W-Wide Flange",
            "M_UB-Universal Beams",
            "UB-Universal Beams",
        ],
        ["brace"] =
        [
            "M_W-Wide Flange",
            "W-Wide Flange",
            "M_Concrete-Rectangular Beam",
            "Concrete-Rectangular Beam",
        ],
        ["footing"] =
        [
            "M_Footing-Rectangular",
            "Footing-Rectangular",
            "M_Pile Cap-Rectangular",
            "Pile Cap-Rectangular",
        ],
    };

    public RevitTypeResolver(Document doc, ImportExportSummary summary)
    {
        _doc = doc;
        _summary = summary;
    }

    public void EnsureMaterials(IEnumerable<ExchangeMaterial> materials)
    {
        var existing = new FilteredElementCollector(_doc)
            .OfClass(typeof(Material))
            .Cast<Material>()
            .ToList();

        foreach (var mat in existing)
        {
            _materials[mat.Name] = mat;
        }

        foreach (var src in materials)
        {
            var found = FindMaterial(src.Id) ?? FindMaterial(src.Name);
            if (found is null)
            {
                var matName = string.IsNullOrWhiteSpace(src.Name) ? src.Id : src.Name;
                if (_materials.TryGetValue(matName, out var byName))
                {
                    found = byName;
                }
                else
                {
                    var matId = Material.Create(_doc, matName);
                    found = _doc.GetElement(matId) as Material;
                    if (found is not null)
                    {
                        _materials[matName] = found;
                        _summary.MaterialsCreated++;
                        TryApplyStructuralAsset(found, src);
                    }
                }
            }

            if (found is not null)
            {
                _materials[src.Id] = found;
                if (!string.IsNullOrWhiteSpace(src.Name))
                {
                    _materials[src.Name] = found;
                }
            }
        }
    }

    private Material? FindMaterial(string? key)
    {
        if (string.IsNullOrWhiteSpace(key))
        {
            return null;
        }
        return _materials.TryGetValue(key, out var mat) ? mat : null;
    }

    private void TryApplyStructuralAsset(Material mat, ExchangeMaterial src)
    {
        try
        {
            var isSteel = string.Equals(src.Category, "steel", StringComparison.OrdinalIgnoreCase);
            var assetClass = isSteel ? StructuralAssetClass.Metal : StructuralAssetClass.Concrete;
            var asset = new StructuralAsset($"{mat.Name}_Asset", assetClass);
            if (src.E is > 0)
            {
                asset.YoungModulus = UnitUtils.ConvertToInternalUnits(src.E.Value, UnitTypeId.Megapascals);
            }
            if (src.Nu is > 0)
            {
                asset.PoissonRatio = src.Nu.Value;
            }
            if (src.Density is > 0)
            {
                asset.Density = UnitUtils.ConvertToInternalUnits(src.Density.Value, UnitTypeId.KilogramsPerCubicMeter);
            }
            if (!isSteel && src.Fc is > 0)
            {
                asset.ConcreteCompression = UnitUtils.ConvertToInternalUnits(src.Fc.Value, UnitTypeId.Megapascals);
            }
            if (isSteel && src.Fy is > 0)
            {
                asset.MinimumYieldStress = UnitUtils.ConvertToInternalUnits(src.Fy.Value, UnitTypeId.Megapascals);
            }
            var pse = PropertySetElement.Create(_doc, asset);
            mat.SetMaterialAspectByPropertySet(MaterialAspect.Structural, pse.Id);
        }
        catch
        {
            // Structural asset parameters are optional if units/template reject them.
        }
    }

    public void TryLoadDefaultFamilies(IEnumerable<string> kindsNeeded)
    {
        var libraryPaths = _doc.Application.GetLibraryPaths();
        if (libraryPaths is null || libraryPaths.Count == 0)
        {
            return;
        }

        foreach (var kind in kindsNeeded.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            if (!DefaultFamilyNames.TryGetValue(kind, out var names))
            {
                continue;
            }

            var bic = CategoryForKind(kind);
            if (bic is null)
            {
                continue;
            }

            var hasAny = new FilteredElementCollector(_doc)
                .OfClass(typeof(FamilySymbol))
                .OfCategory(bic.Value)
                .Any();
            if (hasAny)
            {
                continue;
            }

            foreach (var root in libraryPaths.Values)
            {
                if (string.IsNullOrWhiteSpace(root) || !Directory.Exists(root))
                {
                    continue;
                }

                foreach (var famName in names)
                {
                    var match = Directory.EnumerateFiles(root, $"{famName}.rfa", SearchOption.AllDirectories)
                        .FirstOrDefault();
                    if (match is null)
                    {
                        continue;
                    }

                    try
                    {
                        if (_doc.LoadFamily(match, out _))
                        {
                            break;
                        }
                    }
                    catch
                    {
                        // Ignore load errors for incompatible families.
                    }
                }
            }
        }
    }

    public FamilySymbol? ResolveFamilySymbol(ExchangeSection section, string elementKind)
    {
        var bic = CategoryForKind(elementKind);
        if (bic is null)
        {
            return null;
        }

        var symbols = new FilteredElementCollector(_doc)
            .OfClass(typeof(FamilySymbol))
            .OfCategory(bic.Value)
            .Cast<FamilySymbol>()
            .ToList();

        if (symbols.Count == 0)
        {
            return null;
        }

        var candidates = symbols.Select(ToCandidate).ToList();
        var matched = SectionMatcher.FindBestMatch(section, candidates);
        if (matched is not null)
        {
            var sym = symbols.First(s => s.UniqueId == matched.Key);
            Activate(sym);
            _summary.TypesMatched++;
            return sym;
        }

        var template = PickTemplateSymbol(symbols, section);
        var targetName = string.IsNullOrWhiteSpace(section.Name) ? section.Id : section.Name;
        var existingByName = symbols.FirstOrDefault(s =>
            string.Equals(s.Name, targetName, StringComparison.OrdinalIgnoreCase));
        if (existingByName is not null)
        {
            Activate(existingByName);
            _summary.TypesMatched++;
            return existingByName;
        }

        try
        {
            var uniqueName = MakeUniqueTypeName(symbols.Select(s => s.Name), targetName);
            if (template.Duplicate(uniqueName) is FamilySymbol created)
            {
                ApplySymbolDimensions(created, section);
                ApplySymbolMaterial(created, section.Material);
                Activate(created);
                _summary.TypesCreated++;
                return created;
            }
        }
        catch (Exception ex)
        {
            _summary.Warnings.Add($"Could not create type '{targetName}': {ex.Message}");
        }

        return null;
    }

    public WallType? ResolveWallType(ExchangeSection section)
    {
        var types = new FilteredElementCollector(_doc)
            .OfClass(typeof(WallType))
            .Cast<WallType>()
            .Where(t => t.Kind == WallKind.Basic)
            .ToList();
        if (types.Count == 0)
        {
            return null;
        }

        var candidates = types.Select(t => new SectionCandidate(
            t.UniqueId, t.Name, "wall", ThicknessMm: UnitConverter.FeetToMm(t.Width)
        )).ToList();

        var matched = SectionMatcher.FindBestMatch(section, candidates);
        if (matched is not null)
        {
            _summary.TypesMatched++;
            return types.First(t => t.UniqueId == matched.Key);
        }

        var targetName = string.IsNullOrWhiteSpace(section.Name) ? section.Id : section.Name;
        var template = types[0];
        try
        {
            var uniqueName = MakeUniqueTypeName(types.Select(t => t.Name), targetName);
            if (template.Duplicate(uniqueName) is WallType created)
            {
                if (section.Thickness is > 0)
                {
                    SetCompoundThickness(created, section.Thickness.Value, section.Material);
                }
                _summary.TypesCreated++;
                return created;
            }
        }
        catch (Exception ex)
        {
            _summary.Warnings.Add($"Could not create wall type '{targetName}': {ex.Message}");
        }

        return null;
    }

    public FloorType? ResolveFloorType(ExchangeSection section)
    {
        var types = new FilteredElementCollector(_doc)
            .OfClass(typeof(FloorType))
            .Cast<FloorType>()
            .Where(t => !t.IsFoundationSlab)
            .ToList();
        if (types.Count == 0)
        {
            return null;
        }

        var candidates = types.Select(t =>
        {
            double? thicknessMm = null;
            try
            {
                var cs = t.GetCompoundStructure();
                if (cs is not null)
                {
                    thicknessMm = UnitConverter.FeetToMm(cs.GetWidth());
                }
            }
            catch
            {
                // Ignore non-compound floor types.
            }
            return new SectionCandidate(t.UniqueId, t.Name, "slab", ThicknessMm: thicknessMm);
        }).ToList();

        var matched = SectionMatcher.FindBestMatch(section, candidates);
        if (matched is not null)
        {
            _summary.TypesMatched++;
            return types.First(t => t.UniqueId == matched.Key);
        }

        var targetName = string.IsNullOrWhiteSpace(section.Name) ? section.Id : section.Name;
        var template = types[0];
        try
        {
            var uniqueName = MakeUniqueTypeName(types.Select(t => t.Name), targetName);
            if (template.Duplicate(uniqueName) is FloorType created)
            {
                if (section.Thickness is > 0)
                {
                    SetCompoundThickness(created, section.Thickness.Value, section.Material);
                }
                _summary.TypesCreated++;
                return created;
            }
        }
        catch (Exception ex)
        {
            _summary.Warnings.Add($"Could not create floor type '{targetName}': {ex.Message}");
        }

        return null;
    }

    public RebarBarType? ResolveRebarBarType(double diameterMm)
    {
        var barTypes = new FilteredElementCollector(_doc)
            .OfClass(typeof(RebarBarType))
            .Cast<RebarBarType>()
            .ToList();
        if (barTypes.Count == 0)
        {
            return null;
        }

        var exact = barTypes.FirstOrDefault(b =>
            Math.Abs(UnitConverter.FeetToMm(b.BarModelDiameter) - diameterMm) <= 0.5);
        if (exact is not null)
        {
            return exact;
        }

        try
        {
            var name = MakeUniqueTypeName(barTypes.Select(b => b.Name), $"SA_{diameterMm:0.#}mm");
            if (barTypes[0].Duplicate(name) is RebarBarType created)
            {
                created.BarModelDiameter = UnitConverter.MmToFeet(diameterMm);
                created.BarNominalDiameter = UnitConverter.MmToFeet(diameterMm);
                return created;
            }
        }
        catch
        {
            // Fall back to nearest bar type if duplication fails.
        }

        return barTypes.OrderBy(b => Math.Abs(UnitConverter.FeetToMm(b.BarModelDiameter) - diameterMm)).First();
    }

    private static BuiltInCategory? CategoryForKind(string kind) => kind switch
    {
        "column" => BuiltInCategory.OST_StructuralColumns,
        "beam" or "brace" or "member" => BuiltInCategory.OST_StructuralFraming,
        "footing" => BuiltInCategory.OST_StructuralFoundation,
        _ => null,
    };

    private static SectionCandidate ToCandidate(FamilySymbol sym)
    {
        var width = ReadParamMm(sym, "b", "Width", "bf", "Overall Width");
        var depth = ReadParamMm(sym, "h", "Height", "d", "Overall Depth", "Depth");
        var dia = ReadParamMm(sym, "Diameter", "D", "Dia");
        var len = ReadParamMm(sym, "Length", "L");
        var thickness = ReadParamMm(sym, "Foundation Thickness", "Thickness", "t");
        return new SectionCandidate(sym.UniqueId, sym.Name, sym.Category?.Name ?? "", width, depth, dia, thickness, len);
    }

    private static FamilySymbol PickTemplateSymbol(List<FamilySymbol> symbols, ExchangeSection section)
    {
        var shape = section.Profile?.Shape?.Trim().ToLowerInvariant();
        if (shape == "circle")
        {
            var round = symbols.FirstOrDefault(s =>
                s.FamilyName.Contains("Round", StringComparison.OrdinalIgnoreCase)
                || s.FamilyName.Contains("Circular", StringComparison.OrdinalIgnoreCase));
            if (round is not null)
            {
                return round;
            }
        }
        else if (shape == "i")
        {
            var wide = symbols.FirstOrDefault(s =>
                s.FamilyName.Contains("Flange", StringComparison.OrdinalIgnoreCase)
                || s.FamilyName.Contains("UB", StringComparison.OrdinalIgnoreCase)
                || s.FamilyName.Contains("Steel", StringComparison.OrdinalIgnoreCase));
            if (wide is not null)
            {
                return wide;
            }
        }
        return symbols[0];
    }

    private static void ApplySymbolDimensions(FamilySymbol sym, ExchangeSection section)
    {
        var (w, d, dia, t, len) = SectionMatcher.ExtractDimensionsMm(section);
        if (w is > 0)
        {
            TrySetParamMm(sym, w.Value, "b", "Width", "bf", "Overall Width");
        }
        if (d is > 0)
        {
            TrySetParamMm(sym, d.Value, "h", "Height", "d", "Overall Depth", "Depth");
        }
        if (dia is > 0)
        {
            TrySetParamMm(sym, dia.Value, "Diameter", "D", "Dia", "b");
        }
        if (len is > 0)
        {
            TrySetParamMm(sym, len.Value, "Length", "L");
        }
        if (t is > 0)
        {
            TrySetParamMm(sym, t.Value, "Foundation Thickness", "Thickness", "t");
        }
    }

    private void ApplySymbolMaterial(Element elem, string? materialId)
    {
        var mat = FindMaterial(materialId);
        if (mat is null)
        {
            return;
        }
        var p = elem.get_Parameter(BuiltInParameter.STRUCTURAL_MATERIAL_PARAM)
            ?? elem.LookupParameter("Structural Material")
            ?? elem.LookupParameter("Material");
        if (p is not null && !p.IsReadOnly && p.StorageType == StorageType.ElementId)
        {
            p.Set(mat.Id);
        }
    }

    private void SetCompoundThickness(HostObjAttributes hostType, double thicknessMm, string? materialId)
    {
        var cs = hostType.GetCompoundStructure();
        if (cs is null || cs.LayerCount == 0)
        {
            return;
        }
        var totalFeet = UnitConverter.MmToFeet(thicknessMm);
        var coreIdx = cs.GetFirstCoreLayerIndex();
        if (coreIdx < 0 || coreIdx >= cs.LayerCount)
        {
            coreIdx = 0;
        }
        for (var i = 0; i < cs.LayerCount; i++)
        {
            cs.SetLayerWidth(i, i == coreIdx ? totalFeet : 0.0);
        }
        var mat = FindMaterial(materialId);
        if (mat is not null)
        {
            cs.SetMaterialId(coreIdx, mat.Id);
        }
        hostType.SetCompoundStructure(cs);
    }

    private static void Activate(FamilySymbol symbol)
    {
        if (!symbol.IsActive)
        {
            symbol.Activate();
        }
    }

    private static double? ReadParamMm(Element elem, params string[] names)
    {
        foreach (var name in names)
        {
            var p = elem.LookupParameter(name);
            if (p is not null && p.HasValue && p.StorageType == StorageType.Double)
            {
                return UnitConverter.FeetToMm(p.AsDouble());
            }
        }
        return null;
    }

    private static void TrySetParamMm(Element elem, double mm, params string[] names)
    {
        var feet = UnitConverter.MmToFeet(mm);
        foreach (var name in names)
        {
            var p = elem.LookupParameter(name);
            if (p is not null && !p.IsReadOnly && p.StorageType == StorageType.Double)
            {
                p.Set(feet);
                return;
            }
        }
    }

    private static string MakeUniqueTypeName(IEnumerable<string> existing, string baseName)
    {
        var set = new HashSet<string>(existing, StringComparer.OrdinalIgnoreCase);
        var clean = SanitizeName(baseName);
        if (!set.Contains(clean))
        {
            return clean;
        }
        var i = 2;
        while (set.Contains($"{clean} ({i})"))
        {
            i++;
        }
        return $"{clean} ({i})";
    }

    private static string SanitizeName(string name)
    {
        var invalid = new HashSet<char>(['\\', ':', '{', '}', '[', ']', '|', ';', '<', '>', '?', '`', '~']);
        var chars = name.Trim().Select(c => invalid.Contains(c) ? '_' : c).ToArray();
        return chars.Length > 0 ? new string(chars) : "SAEngine Type";
    }
}
