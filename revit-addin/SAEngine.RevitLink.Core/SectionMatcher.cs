namespace SAEngine.RevitLink.Core;

public sealed record SectionCandidate(
    string Key,
    string Name,
    string Kind,
    double? WidthMm = null,
    double? DepthMm = null,
    double? DiameterMm = null,
    double? ThicknessMm = null,
    double? LengthMm = null
);

public static class SectionMatcher
{
    public static (double? WidthMm, double? DepthMm, double? DiameterMm, double? ThicknessMm, double? LengthMm)
        ExtractDimensionsMm(ExchangeSection section)
    {
        if (section.Profile is { } p)
        {
            var shape = p.Shape?.Trim().ToLowerInvariant();
            return shape switch
            {
                "rectangle" => (p.XDim, p.YDim, null, null, null),
                "circle" => (null, null, p.Radius is > 0 ? p.Radius.Value * 2.0 : null, null, null),
                "i" or "t" or "l" or "u" or "channel" or "box" or "rhs" =>
                    (p.OverallWidth, p.OverallDepth, null, null, null),
                "chs" or "pipe" => (null, null, p.OverallWidth ?? p.OverallDepth, null, null),
                _ => (p.XDim ?? p.OverallWidth, p.YDim ?? p.OverallDepth, null, null, null),
            };
        }

        return (section.Width, null, null, section.Thickness, section.Length);
    }

    public static SectionCandidate? FindBestMatch(
        ExchangeSection section,
        IReadOnlyList<SectionCandidate> candidates,
        double toleranceMm = UnitConverter.PositionToleranceMm
    )
    {
        foreach (var c in candidates)
        {
            if (string.Equals(c.Name, section.Id, StringComparison.OrdinalIgnoreCase))
            {
                return c;
            }
        }

        if (!string.IsNullOrWhiteSpace(section.Name))
        {
            foreach (var c in candidates)
            {
                if (string.Equals(c.Name.Trim(), section.Name.Trim(), StringComparison.OrdinalIgnoreCase))
                {
                    return c;
                }
            }
        }

        var (w, d, dia, t, len) = ExtractDimensionsMm(section);
        foreach (var c in candidates)
        {
            if (t is > 0 && c.ThicknessMm is > 0 && Math.Abs(t.Value - c.ThicknessMm.Value) <= toleranceMm)
            {
                return c;
            }

            if (dia is > 0 && c.DiameterMm is > 0 && Math.Abs(dia.Value - c.DiameterMm.Value) <= toleranceMm)
            {
                return c;
            }

            if (len is > 0 && w is > 0 && c.LengthMm is > 0 && c.WidthMm is > 0)
            {
                var direct = Math.Abs(len.Value - c.LengthMm.Value) <= toleranceMm
                    && Math.Abs(w.Value - c.WidthMm.Value) <= toleranceMm;
                var swapped = Math.Abs(len.Value - c.WidthMm.Value) <= toleranceMm
                    && Math.Abs(w.Value - c.LengthMm.Value) <= toleranceMm;
                if (direct || swapped)
                {
                    return c;
                }
            }

            if (w is > 0 && d is > 0 && c.WidthMm is > 0 && c.DepthMm is > 0)
            {
                if (Math.Abs(w.Value - c.WidthMm.Value) <= toleranceMm
                    && Math.Abs(d.Value - c.DepthMm.Value) <= toleranceMm)
                {
                    return c;
                }
            }
        }

        return null;
    }
}
