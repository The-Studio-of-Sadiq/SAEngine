using System.Text.Json;
using System.Text.Json.Serialization;

namespace SAEngine.RevitLink.Core;

public static class ExchangeSchema
{
    public const string SchemaId = "saengine.structuralExchange/1";
    public const string ParameterName = "SAEngine Id";

    public static readonly string[] AllKinds =
    [
        "column",
        "beam",
        "wall",
        "slab",
        "footing",
        "brace",
        "member",
        "area",
    ];

    public static readonly string[] RevitExportScope =
    [
        "column",
        "beam",
        "wall",
        "slab",
        "footing",
        "brace",
    ];
}

public sealed class ExchangeDocument
{
    [JsonPropertyName("schema")]
    public string Schema { get; set; } = ExchangeSchema.SchemaId;

    [JsonPropertyName("origin")]
    public ExchangeOrigin? Origin { get; set; }

    [JsonPropertyName("project")]
    public ExchangeProject? Project { get; set; }

    [JsonPropertyName("units")]
    public ExchangeUnits Units { get; set; } = new();

    [JsonPropertyName("scope")]
    public List<string> Scope { get; set; } = [.. ExchangeSchema.AllKinds];

    [JsonPropertyName("levels")]
    public List<ExchangeLevel> Levels { get; set; } = [];

    [JsonPropertyName("grids")]
    public List<ExchangeGrid> Grids { get; set; } = [];

    [JsonPropertyName("materials")]
    public List<ExchangeMaterial> Materials { get; set; } = [];

    [JsonPropertyName("sections")]
    public List<ExchangeSection> Sections { get; set; } = [];

    [JsonPropertyName("elements")]
    public List<ExchangeElement> Elements { get; set; } = [];

    [JsonPropertyName("rebar")]
    public List<ExchangeRebar> Rebar { get; set; } = [];

    [JsonPropertyName("notes")]
    public List<string> Notes { get; set; } = [];
}

public sealed class ExchangeOrigin
{
    [JsonPropertyName("application")]
    public string Application { get; set; } = "Revit";

    [JsonPropertyName("version")]
    public string Version { get; set; } = "2027";

    [JsonPropertyName("written")]
    public string? Written { get; set; }

    [JsonPropertyName("document")]
    public string? Document { get; set; }
}

public sealed class ExchangeProject
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("type")]
    public string Type { get; set; } = "building";
}

public sealed class ExchangeUnits
{
    [JsonPropertyName("length")]
    public string Length { get; set; } = "mm";

    [JsonPropertyName("angle")]
    public string Angle { get; set; } = "deg";

    [JsonPropertyName("stress")]
    public string Stress { get; set; } = "MPa";

    [JsonPropertyName("density")]
    public string Density { get; set; } = "kg/m3";
}

public sealed class ExchangeLevel
{
    [JsonPropertyName("id")]
    public string? Id { get; set; }

    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("elevation")]
    public double Elevation { get; set; }

    [JsonPropertyName("revitId")]
    public string? RevitId { get; set; }
}

public sealed class ExchangeGridArc
{
    [JsonPropertyName("center")]
    public List<double> Center { get; set; } = [];

    [JsonPropertyName("radius")]
    public double Radius { get; set; }

    [JsonPropertyName("startAngle")]
    public double StartAngle { get; set; }

    [JsonPropertyName("endAngle")]
    public double EndAngle { get; set; }
}

public sealed class ExchangeGrid
{
    [JsonPropertyName("id")]
    public string? Id { get; set; }

    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("axis")]
    public string? Axis { get; set; }

    [JsonPropertyName("position")]
    public double? Position { get; set; }

    [JsonPropertyName("start")]
    public List<double>? Start { get; set; }

    [JsonPropertyName("end")]
    public List<double>? End { get; set; }

    [JsonPropertyName("arc")]
    public ExchangeGridArc? Arc { get; set; }

    [JsonPropertyName("revitId")]
    public string? RevitId { get; set; }
}

public sealed class ExchangeMaterial
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("category")]
    public string Category { get; set; } = "concrete";

    [JsonPropertyName("E")]
    public double? E { get; set; }

    [JsonPropertyName("nu")]
    public double? Nu { get; set; }

    [JsonPropertyName("density")]
    public double? Density { get; set; }

    [JsonPropertyName("fc")]
    public double? Fc { get; set; }

    [JsonPropertyName("fy")]
    public double? Fy { get; set; }

    [JsonPropertyName("fu")]
    public double? Fu { get; set; }

    [JsonPropertyName("grade")]
    public string? Grade { get; set; }
}

public sealed class ExchangeProfile
{
    [JsonPropertyName("shape")]
    public string Shape { get; set; } = "rectangle";

    [JsonPropertyName("xDim")]
    public double? XDim { get; set; }

    [JsonPropertyName("yDim")]
    public double? YDim { get; set; }

    [JsonPropertyName("radius")]
    public double? Radius { get; set; }

    [JsonPropertyName("overallWidth")]
    public double? OverallWidth { get; set; }

    [JsonPropertyName("overallDepth")]
    public double? OverallDepth { get; set; }

    [JsonPropertyName("webThickness")]
    public double? WebThickness { get; set; }

    [JsonPropertyName("flangeThickness")]
    public double? FlangeThickness { get; set; }

    [JsonPropertyName("wallThickness")]
    public double? WallThickness { get; set; }

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? Extra { get; set; }
}

public sealed class ExchangeSection
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("kind")]
    public string Kind { get; set; } = "";

    [JsonPropertyName("material")]
    public string? Material { get; set; }

    [JsonPropertyName("profile")]
    public ExchangeProfile? Profile { get; set; }

    [JsonPropertyName("thickness")]
    public double? Thickness { get; set; }

    [JsonPropertyName("length")]
    public double? Length { get; set; }

    [JsonPropertyName("width")]
    public double? Width { get; set; }

    [JsonPropertyName("waistThickness")]
    public double? WaistThickness { get; set; }

    [JsonPropertyName("structural")]
    public bool? Structural { get; set; }

    [JsonPropertyName("footingType")]
    public string? FootingType { get; set; }

    [JsonPropertyName("reinforcement")]
    public JsonElement? Reinforcement { get; set; }
}

public sealed class ExchangeElement
{
    [JsonPropertyName("id")]
    public string? Id { get; set; }

    [JsonPropertyName("kind")]
    public string Kind { get; set; } = "";

    [JsonPropertyName("section")]
    public string? Section { get; set; }

    [JsonPropertyName("owner")]
    public string? Owner { get; set; }

    [JsonPropertyName("name")]
    public string? Name { get; set; }

    [JsonPropertyName("revitId")]
    public string? RevitId { get; set; }

    [JsonPropertyName("curve")]
    public List<List<double>>? Curve { get; set; }

    [JsonPropertyName("point")]
    public List<double>? Point { get; set; }

    [JsonPropertyName("outline")]
    public List<List<double>>? Outline { get; set; }

    [JsonPropertyName("openings")]
    public List<List<List<double>>>? Openings { get; set; }

    [JsonPropertyName("rotation")]
    public double? Rotation { get; set; }

    [JsonPropertyName("level")]
    public string? Level { get; set; }

    [JsonPropertyName("baseLevel")]
    public string? BaseLevel { get; set; }

    [JsonPropertyName("topLevel")]
    public string? TopLevel { get; set; }

    [JsonPropertyName("bottom")]
    public double? Bottom { get; set; }

    [JsonPropertyName("top")]
    public double? Top { get; set; }

    [JsonPropertyName("reference")]
    public string? Reference { get; set; }
}

public sealed class ExchangeRebar
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("host")]
    public string Host { get; set; } = "";

    [JsonPropertyName("mark")]
    public string Mark { get; set; } = "";

    [JsonPropertyName("role")]
    public string Role { get; set; } = "";

    [JsonPropertyName("dia")]
    public double Dia { get; set; }

    [JsonPropertyName("shape")]
    public string Shape { get; set; } = "";

    [JsonPropertyName("length")]
    public double Length { get; set; }

    [JsonPropertyName("count")]
    public int Count { get; set; }

    [JsonPropertyName("transverse")]
    public bool Transverse { get; set; }

    [JsonPropertyName("material")]
    public string? Material { get; set; }

    [JsonPropertyName("lines")]
    public List<List<List<double>>> Lines { get; set; } = [];
}

public static class ExchangeJson
{
    private static readonly JsonSerializerOptions ReadOptions = new()
    {
        PropertyNameCaseInsensitive = false,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
    };

    private static readonly JsonSerializerOptions WriteOptions = new()
    {
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    public static ExchangeDocument Parse(string json)
    {
        var doc = JsonSerializer.Deserialize<ExchangeDocument>(json, ReadOptions)
            ?? throw new InvalidDataException("Exchange file is empty.");
        Validate(doc);
        return doc;
    }

    public static ExchangeDocument Read(string path)
    {
        var json = File.ReadAllText(path);
        return Parse(json);
    }

    public static string Serialize(ExchangeDocument doc)
    {
        return JsonSerializer.Serialize(doc, WriteOptions) + "\n";
    }

    public static void Write(string path, ExchangeDocument doc)
    {
        var dir = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(dir))
        {
            Directory.CreateDirectory(dir);
        }
        File.WriteAllText(path, Serialize(doc), new System.Text.UTF8Encoding(false));
    }

    public static void Validate(ExchangeDocument doc)
    {
        if (!string.Equals(doc.Schema, ExchangeSchema.SchemaId, StringComparison.Ordinal))
        {
            throw new InvalidDataException(
                $"Unsupported schema '{doc.Schema}'. Expected '{ExchangeSchema.SchemaId}'."
            );
        }

        if (!string.Equals(doc.Units.Length, "mm", StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(doc.Units.Angle, "deg", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException(
                $"Exchange file units must be mm and deg (got '{doc.Units.Length}' and '{doc.Units.Angle}')."
            );
        }
    }
}
