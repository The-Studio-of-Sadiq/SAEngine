namespace SAEngine.RevitLink.Core;

public static class UnitConverter
{
    public const double MmPerFoot = 304.8;
    public const double PositionToleranceMm = 1.0;
    public const double LevelToleranceMm = 5.0;
    public const double AngleToleranceDeg = 0.5;
    public const double ShortCurveToleranceMm = 2.0;

    public static double MmToFeet(double mm) => mm / MmPerFoot;

    public static double FeetToMm(double feet) => feet * MmPerFoot;

    public static double RoundMm(double mm) => Math.Round(mm, 1, MidpointRounding.AwayFromZero);

    public static double FeetToRoundedMm(double feet) => RoundMm(FeetToMm(feet));

    public static double DegToRad(double degrees) => degrees * Math.PI / 180.0;

    public static double RadToDeg(double radians) => radians * 180.0 / Math.PI;

    public static double NormalizeDeg(double degrees)
    {
        var d = degrees % 360.0;
        if (d < 0)
        {
            d += 360.0;
        }
        return Math.Round(d, 2, MidpointRounding.AwayFromZero);
    }

    public static double DistanceMm(IReadOnlyList<double> a, IReadOnlyList<double> b)
    {
        var dx = a[0] - b[0];
        var dy = a[1] - b[1];
        var dz = (a.Count > 2 && b.Count > 2) ? (a[2] - b[2]) : 0.0;
        return Math.Sqrt(dx * dx + dy * dy + dz * dz);
    }

    public static bool ArePointsCloseMm(IReadOnlyList<double>? a, IReadOnlyList<double>? b, double tol = PositionToleranceMm)
    {
        if (a is null || b is null || a.Count != b.Count)
        {
            return false;
        }
        for (var i = 0; i < a.Count; i++)
        {
            if (Math.Abs(a[i] - b[i]) > tol)
            {
                return false;
            }
        }
        return true;
    }
}
