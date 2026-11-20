namespace SAEngine.RevitLink.Core;

public static class GridHelper
{
    public const double DefaultExtentPaddingMm = 3000.0;

    public static (string? Axis, double Position) ClassifyGrid(
        IReadOnlyList<double>? start,
        IReadOnlyList<double>? end,
        double toleranceMm = UnitConverter.PositionToleranceMm
    )
    {
        if (start is null || end is null || start.Count < 2 || end.Count < 2)
        {
            return (null, 0.0);
        }

        if (Math.Abs(start[0] - end[0]) <= toleranceMm)
        {
            return ("x", UnitConverter.RoundMm((start[0] + end[0]) / 2.0));
        }

        if (Math.Abs(start[1] - end[1]) <= toleranceMm)
        {
            return ("y", UnitConverter.RoundMm((start[1] + end[1]) / 2.0));
        }

        return (null, 0.0);
    }

    public static ((double X, double Y) Start, (double X, double Y) End)? ResolveEndpointsMm(
        ExchangeGrid grid,
        double minX,
        double maxX,
        double minY,
        double maxY
    )
    {
        if (grid.Start is { Count: >= 2 } && grid.End is { Count: >= 2 })
        {
            var dx = grid.End[0] - grid.Start[0];
            var dy = grid.End[1] - grid.Start[1];
            if (dx * dx + dy * dy >= UnitConverter.ShortCurveToleranceMm * UnitConverter.ShortCurveToleranceMm)
            {
                return ((grid.Start[0], grid.Start[1]), (grid.End[0], grid.End[1]));
            }
        }

        if (grid.Position is null || string.IsNullOrWhiteSpace(grid.Axis))
        {
            return null;
        }

        var pos = grid.Position.Value;
        if (string.Equals(grid.Axis, "x", StringComparison.OrdinalIgnoreCase))
        {
            var lo = Math.Min(minY, maxY) - DefaultExtentPaddingMm;
            var hi = Math.Max(minY, maxY) + DefaultExtentPaddingMm;
            if (Math.Abs(hi - lo) < 1000.0)
            {
                lo = -5000.0;
                hi = 15000.0;
            }
            return ((pos, lo), (pos, hi));
        }

        if (string.Equals(grid.Axis, "y", StringComparison.OrdinalIgnoreCase))
        {
            var lo = Math.Min(minX, maxX) - DefaultExtentPaddingMm;
            var hi = Math.Max(minX, maxX) + DefaultExtentPaddingMm;
            if (Math.Abs(hi - lo) < 1000.0)
            {
                lo = -5000.0;
                hi = 15000.0;
            }
            return ((lo, pos), (hi, pos));
        }

        return null;
    }
}
