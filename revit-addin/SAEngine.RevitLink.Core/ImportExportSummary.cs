using System.Text;

namespace SAEngine.RevitLink.Core;

public sealed class ImportExportSummary
{
    public int LevelsCreated { get; set; }
    public int LevelsUpdated { get; set; }
    public int GridsCreated { get; set; }
    public int GridsUpdated { get; set; }
    public int MaterialsCreated { get; set; }
    public int TypesMatched { get; set; }
    public int TypesCreated { get; set; }
    public int ElementsCreated { get; set; }
    public int ElementsUpdated { get; set; }
    public int ElementsSkipped { get; set; }
    public int RebarCreated { get; set; }
    public int RebarSkipped { get; set; }

    public List<string> UnmatchedSections { get; } = [];
    public List<string> RebarNotes { get; } = [];
    public List<string> Warnings { get; } = [];

    public string FormatImportReport(string fileName)
    {
        var sb = new StringBuilder();
        sb.AppendLine($"Imported: {fileName}");
        sb.AppendLine();
        sb.AppendLine($"Levels: {LevelsCreated} created, {LevelsUpdated} updated");
        sb.AppendLine($"Grids: {GridsCreated} created, {GridsUpdated} updated");
        sb.AppendLine($"Materials created: {MaterialsCreated}");
        sb.AppendLine($"Types: {TypesMatched} matched, {TypesCreated} created, {UnmatchedSections.Count} unmatched");
        sb.AppendLine($"Elements: {ElementsCreated} created, {ElementsUpdated} updated, {ElementsSkipped} skipped");
        sb.AppendLine($"Rebar sets: {RebarCreated} placed, {RebarSkipped} skipped");

        if (UnmatchedSections.Count > 0)
        {
            sb.AppendLine();
            sb.AppendLine("Unmatched sections (no loaded family available to match or duplicate):");
            foreach (var s in UnmatchedSections.Take(10))
            {
                sb.AppendLine($"  - {s}");
            }
            if (UnmatchedSections.Count > 10)
            {
                sb.AppendLine($"  ... and {UnmatchedSections.Count - 10} more.");
            }
        }

        if (RebarNotes.Count > 0)
        {
            sb.AppendLine();
            sb.AppendLine("Rebar notes:");
            foreach (var note in RebarNotes.Take(8))
            {
                sb.AppendLine($"  - {note}");
            }
            if (RebarNotes.Count > 8)
            {
                sb.AppendLine($"  ... and {RebarNotes.Count - 8} more.");
            }
        }

        if (Warnings.Count > 0)
        {
            sb.AppendLine();
            sb.AppendLine("Warnings:");
            foreach (var w in Warnings.Take(8))
            {
                sb.AppendLine($"  - {w}");
            }
            if (Warnings.Count > 8)
            {
                sb.AppendLine($"  ... and {Warnings.Count - 8} more.");
            }
        }

        return sb.ToString().TrimEnd();
    }
}
