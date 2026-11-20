using Autodesk.Revit.DB;

namespace SAEngine.RevitLink;

internal sealed class FailureHandler : IFailuresPreprocessor
{
    public List<string> Messages { get; } = [];

    public FailureProcessingResult PreprocessFailures(FailuresAccessor failuresAccessor)
    {
        var messages = failuresAccessor.GetFailureMessages();
        foreach (var msg in messages)
        {
            var text = msg.GetDescriptionText();
            if (!string.IsNullOrWhiteSpace(text))
            {
                Messages.Add(text);
            }

            var severity = msg.GetSeverity();
            if (severity == FailureSeverity.Warning)
            {
                failuresAccessor.DeleteWarning(msg);
            }
            else if (msg.HasResolutions())
            {
                failuresAccessor.ResolveFailure(msg);
                return FailureProcessingResult.ProceedWithCommit;
            }
        }

        return FailureProcessingResult.Continue;
    }
}
