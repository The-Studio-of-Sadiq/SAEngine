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

    public static ((double X, double Y) Center, double Radius, double StartAngleDeg, double EndAngleDeg)?
        ResolveArcMm(ExchangeGrid grid)
    {
        var arc = grid.Arc;
        if (arc is null || arc.Center is not { Count: >= 2 })
        {
            return null;
        }

        if (double.IsNaN(arc.Radius) || double.IsInfinity(arc.Radius) || arc.Radius <= UnitConverter.ShortCurveToleranceMm)
        {
            return null;
        }

        var startDeg = arc.StartAngle;
        var endDeg = arc.EndAngle;
        if (double.IsNaN(startDeg) || double.IsNaN(endDeg) || double.IsInfinity(startDeg) || double.IsInfinity(endDeg))
        {
            return null;
        }

        if (Math.Abs(endDeg - startDeg) <= 1e-4)
        {
            return null;
        }

        while (endDeg <= startDeg)
        {
            endDeg += 360.0;
        }

        var sweep = endDeg - startDeg;
        if (sweep <= 1e-4 || sweep >= 360.0 - 1e-4)
        {
            return null;
        }

        return ((arc.Center[0], arc.Center[1]), arc.Radius, startDeg, endDeg);
    }

    public static ((double X, double Y) Start, (double X, double Y) End) ComputeArcEndpointsMm(
        (double X, double Y) center,
        double radius,
        double startAngleDeg,
        double endAngleDeg
    )
    {
        var sr = UnitConverter.DegToRad(startAngleDeg);
        var er = UnitConverter.DegToRad(endAngleDeg);
        return (
            (center.X + radius * Math.Cos(sr), center.Y + radius * Math.Sin(sr)),
            (center.X + radius * Math.Cos(er), center.Y + radius * Math.Sin(er))
        );
    }

    public static (ExchangeGridArc Arc, List<double> Start, List<double> End) BuildExchangeArcMm(
        (double X, double Y) centerMm,
        double radiusMm,
        (double X, double Y) startMm,
        (double X, double Y) endMm,
        double sweepDeg,
        bool clockwise
    )
    {
        var p0 = clockwise ? endMm : startMm;
        var p1 = clockwise ? startMm : endMm;
        var startDeg = UnitConverter.RadToDeg(Math.Atan2(p0.Y - centerMm.Y, p0.X - centerMm.X));
        var endDeg = startDeg + sweepDeg;

        var arc = new ExchangeGridArc
        {
            Center = [UnitConverter.RoundMm(centerMm.X), UnitConverter.RoundMm(centerMm.Y)],
            Radius = UnitConverter.RoundMm(radiusMm),
            StartAngle = UnitConverter.RoundMm(startDeg),
            EndAngle = UnitConverter.RoundMm(endDeg),
        };
        var start = new List<double> { UnitConverter.RoundMm(p0.X), UnitConverter.RoundMm(p0.Y) };
        var end = new List<double> { UnitConverter.RoundMm(p1.X), UnitConverter.RoundMm(p1.Y) };
        return (arc, start, end);
    }
}
