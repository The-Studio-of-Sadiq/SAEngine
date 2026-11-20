using Autodesk.Revit.DB;
using Autodesk.Revit.DB.ExtensibleStorage;
using SAEngine.RevitLink.Core;

namespace SAEngine.RevitLink;

internal static class ParameterStorage
{
    private static readonly Guid SchemaGuid = new("A4C7B2E1-9D38-4F6B-8C12-7E5A9B3D1024");
    private const string SchemaName = "SAEngineExchangeId";
    private const string FieldName = "SAEngineId";

    private static readonly BuiltInCategory[] TrackedCategories =
    [
        BuiltInCategory.OST_Levels,
        BuiltInCategory.OST_Grids,
        BuiltInCategory.OST_StructuralColumns,
        BuiltInCategory.OST_StructuralFraming,
        BuiltInCategory.OST_Walls,
        BuiltInCategory.OST_Floors,
        BuiltInCategory.OST_StructuralFoundation,
    ];

    public static void EnsureParameter(Document doc)
    {
        if (HasProjectParameter(doc, ExchangeSchema.ParameterName))
        {
            return;
        }

        var app = doc.Application;
        var previousSharedFile = app.SharedParametersFilename;
        var tempFile = Path.Combine(Path.GetTempPath(), $"SAEngine_{Guid.NewGuid():N}.txt");
        try
        {
            File.WriteAllText(tempFile, string.Empty);
            app.SharedParametersFilename = tempFile;
            var defFile = app.OpenSharedParameterFile();
            if (defFile is null)
            {
                return;
            }

            var group = defFile.Groups.get_Item("SAEngine") ?? defFile.Groups.Create("SAEngine");
            var opts = new ExternalDefinitionCreationOptions(ExchangeSchema.ParameterName, SpecTypeId.String.Text)
            {
                Visible = true,
                UserModifiable = false,
                Description = "Persistent element identifier from SAEngine structural exchange.",
            };
            var definition = group.Definitions.get_Item(ExchangeSchema.ParameterName) ?? group.Definitions.Create(opts);

            var catSet = app.Create.NewCategorySet();
            foreach (var bic in TrackedCategories)
            {
                var cat = Category.GetCategory(doc, bic);
                if (cat is not null && cat.AllowsBoundParameters)
                {
                    catSet.Insert(cat);
                }
            }

            if (!catSet.IsEmpty)
            {
                var binding = app.Create.NewInstanceBinding(catSet);
                doc.ParameterBindings.Insert(definition, binding, GroupTypeId.IdentityData);
            }
        }
        finally
        {
            app.SharedParametersFilename = previousSharedFile ?? string.Empty;
            try
            {
                if (File.Exists(tempFile))
                {
                    File.Delete(tempFile);
                }
            }
            catch
            {
                // Best-effort temp cleanup.
            }
        }
    }

    private static bool HasProjectParameter(Document doc, string name)
    {
        var it = doc.ParameterBindings.ForwardIterator();
        it.Reset();
        while (it.MoveNext())
        {
            if (it.Key is Definition def && string.Equals(def.Name, name, StringComparison.Ordinal))
            {
                return true;
            }
        }
        return false;
    }

    public static string? GetId(Element element)
    {
        var param = element.LookupParameter(ExchangeSchema.ParameterName);
        if (param is not null && param.HasValue && param.StorageType == StorageType.String)
        {
            var value = param.AsString();
            if (!string.IsNullOrWhiteSpace(value))
            {
                return value.Trim();
            }
        }

        var schema = Schema.Lookup(SchemaGuid);
        if (schema is not null)
        {
            var entity = element.GetEntity(schema);
            if (entity.IsValid())
            {
                var value = entity.Get<string>(FieldName);
                if (!string.IsNullOrWhiteSpace(value))
                {
                    return value.Trim();
                }
            }
        }

        return null;
    }

    public static void SetId(Element element, string? saengineId)
    {
        if (string.IsNullOrWhiteSpace(saengineId))
        {
            return;
        }

        var param = element.LookupParameter(ExchangeSchema.ParameterName);
        if (param is not null && !param.IsReadOnly && param.StorageType == StorageType.String)
        {
            param.Set(saengineId);
        }

        var schema = GetOrCreateSchema();
        var entity = new Entity(schema);
        entity.Set(FieldName, saengineId);
        element.SetEntity(entity);
    }

    private static Schema GetOrCreateSchema()
    {
        var existing = Schema.Lookup(SchemaGuid);
        if (existing is not null)
        {
            return existing;
        }

        var builder = new SchemaBuilder(SchemaGuid);
        builder.SetSchemaName(SchemaName);
        builder.SetReadAccessLevel(AccessLevel.Public);
        builder.SetWriteAccessLevel(AccessLevel.Public);
        builder.AddSimpleField(FieldName, typeof(string));
        return builder.Finish();
    }
}
