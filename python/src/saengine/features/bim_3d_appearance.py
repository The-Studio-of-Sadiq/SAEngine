"""BIM 3D appearance and material feature buttons."""

from __future__ import annotations

from typing import Any

from saengine.features import FeatureContext, checkbox, feature, number, result, select, table, text
from saengine.features.bim_common import require_bim


@feature(
    "bim3dAppearance.paintMaterial",
    "Paint Material",
    part="bim",
    fields=[
        text("elementId", "Element id", "C1"),
        text("material", "Material name", "Concrete"),
        select(
            "method",
            "Paint method",
            [("face", "Selected face"), ("element", "Whole element")],
            "element",
        ),
    ],
)
def paint_material(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply a temporary material paint to an element."""
    data = require_bim(ctx)
    ids = {e["id"] for e in data["elements"] if isinstance(e, dict)}
    if values["elementId"].strip() not in ids:
        from saengine.features import FeatureInputError

        raise FeatureInputError("Enter an element id that exists in the BIM model.")
    return result(
        summary={
            "elementId": values["elementId"],
            "material": values["material"],
            "method": values["method"],
        }
    )


@feature(
    "bim3dAppearance.materialBrowser",
    "Material Browser",
    part="bim",
    fields=[text("filter", "Material name filter", "")],
)
def material_browser(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List unique object types as material-browser categories."""
    data = require_bim(ctx)
    needle = str(values["filter"]).strip().lower()
    types = sorted(
        {
            str(e.get("type", ""))
            for e in data["elements"]
            if isinstance(e, dict) and (not needle or needle in str(e.get("type", "")).lower())
        }
    )
    return result(
        summary={"materialCount": len(types), "filter": values["filter"]},
        tables=[
            table("Materials", [("material", "Material or type")], [{"material": v} for v in types])
        ],
    )


@feature(
    "bim3dAppearance.textureMap",
    "Texture Map",
    part="bim",
    fields=[
        text("texturePath", "Texture file path", ""),
        select(
            "mapping", "Mapping method", [("planar", "Planar"), ("box", "Box"), ("uv", "UV")], "uv"
        ),
        number("scale", "Texture scale", 1.0, unit="m", min=0.001),
    ],
)
def texture_map(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure a texture map."""
    require_bim(ctx)
    return result(
        summary={
            "texturePath": values["texturePath"],
            "mapping": values["mapping"],
            "scaleM": values["scale"],
        }
    )


@feature(
    "bim3dAppearance.resetOverrides",
    "Reset Overrides",
    part="bim",
    fields=[
        checkbox("materials", "Reset material overrides", True),
        checkbox("visibility", "Reset visibility overrides", True),
        checkbox("colour", "Reset colour overrides", True),
    ],
)
def reset_overrides(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Reset selected temporary 3D overrides."""
    require_bim(ctx)
    return result(
        summary={
            "resetMaterials": bool(values["materials"]),
            "resetVisibility": bool(values["visibility"]),
            "resetColour": bool(values["colour"]),
        }
    )


@feature(
    "bim3dAppearance.pbrMaterialShader",
    "PBR Material Shader",
    part="bim",
    fields=[
        number("roughness", "Surface roughness", 0.5, unit="", min=0, max=1),
        number("metallic", "Metallic fraction", 0.0, unit="", min=0, max=1),
        number("reflectance", "Reflectance", 0.5, unit="", min=0, max=1),
    ],
)
def pbr_material_shader(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure physically based material parameters."""
    require_bim(ctx)
    return result(
        summary={
            "roughness": values["roughness"],
            "metallicFraction": values["metallic"],
            "reflectance": values["reflectance"],
        }
    )


@feature(
    "bim3dAppearance.edgeLines",
    "Edge Lines",
    part="bim",
    fields=[
        checkbox("enabled", "Show edge lines", True),
        number("width", "Line width", 1.0, unit="px", min=0.5, max=5),
        select(
            "colour", "Line colour", [("dark", "Dark"), ("grey", "Grey"), ("blue", "Blue")], "dark"
        ),
    ],
)
def edge_lines(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure visible element edge lines."""
    require_bim(ctx)
    return result(
        summary={
            "enabled": bool(values["enabled"]),
            "widthPx": values["width"],
            "colour": values["colour"],
        }
    )


@feature(
    "bim3dAppearance.silhouettes",
    "Silhouettes",
    part="bim",
    fields=[
        checkbox("enabled", "Draw silhouettes", True),
        number("width", "Silhouette width", 1.5, unit="px", min=0.5, max=5),
    ],
)
def silhouettes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure model silhouette rendering."""
    require_bim(ctx)
    return result(summary={"enabled": bool(values["enabled"]), "widthPx": values["width"]})


@feature(
    "bim3dAppearance.transparency",
    "Transparency",
    part="bim",
    fields=[
        number("opacity", "Element opacity", 70.0, unit="%", min=0, max=100),
        select(
            "scope",
            "Transparency scope",
            [
                ("all", "All elements"),
                ("category", "Selected category"),
                ("element", "Selected elements"),
            ],
            "all",
        ),
    ],
)
def transparency(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure view transparency."""
    require_bim(ctx)
    return result(summary={"opacityPercent": values["opacity"], "scope": values["scope"]})


@feature(
    "bim3dAppearance.ambientShadows",
    "Ambient Shadows",
    part="bim",
    fields=[
        checkbox("enabled", "Enable ambient shadows", True),
        number("intensity", "Shadow intensity", 30.0, unit="%", min=0, max=100),
    ],
)
def ambient_shadows(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure ambient-occlusion-style shadows."""
    require_bim(ctx)
    return result(
        summary={"enabled": bool(values["enabled"]), "intensityPercent": values["intensity"]}
    )


@feature(
    "bim3dAppearance.skySettings",
    "Sky Settings",
    part="bim",
    fields=[
        select(
            "condition",
            "Sky condition",
            [("clear", "Clear"), ("overcast", "Overcast"), ("night", "Night")],
            "clear",
        ),
        number("brightness", "Sky brightness", 70.0, unit="%", min=0, max=100),
    ],
)
def sky_settings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure the sky backdrop."""
    require_bim(ctx)
    return result(
        summary={"condition": values["condition"], "brightnessPercent": values["brightness"]}
    )


@feature(
    "bim3dAppearance.groundPlane",
    "Ground Plane",
    part="bim",
    fields=[
        checkbox("enabled", "Show ground plane", True),
        number("elevation", "Ground elevation", 0.0, unit="mm"),
        select(
            "surface",
            "Surface",
            [("grass", "Grass"), ("concrete", "Concrete"), ("water", "Water")],
            "concrete",
        ),
    ],
)
def ground_plane(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure a ground plane in the 3D view."""
    require_bim(ctx)
    return result(
        summary={
            "enabled": bool(values["enabled"]),
            "elevationMm": values["elevation"],
            "surface": values["surface"],
        }
    )


@feature(
    "bim3dAppearance.gradientFill",
    "Gradient Fill",
    part="bim",
    fields=[
        checkbox("enabled", "Enable gradient background", True),
        select(
            "direction",
            "Gradient direction",
            [("vertical", "Vertical"), ("horizontal", "Horizontal"), ("radial", "Radial")],
            "vertical",
        ),
    ],
)
def gradient_fill(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure a gradient fill backdrop."""
    require_bim(ctx)
    return result(summary={"enabled": bool(values["enabled"]), "direction": values["direction"]})


@feature(
    "bim3dAppearance.imageBackdrop",
    "Image Backdrop",
    part="bim",
    fields=[
        text("imagePath", "Backdrop image path", ""),
        checkbox("stretch", "Stretch image", True),
        number("opacity", "Backdrop opacity", 100.0, unit="%", min=0, max=100),
    ],
)
def image_backdrop(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure an image-backed 3D presentation."""
    require_bim(ctx)
    return result(
        summary={
            "imagePath": values["imagePath"],
            "stretch": bool(values["stretch"]),
            "opacityPercent": values["opacity"],
        }
    )


@feature(
    "bim3dAppearance.sunPath",
    "Sun Path",
    part="bim",
    fields=[
        checkbox("enabled", "Show sun path", True),
        number("latitude", "Latitude", 23.8, unit="°"),
        number("longitude", "Longitude", 90.4, unit="°"),
    ],
)
def sun_path(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure a sun-path overlay."""
    require_bim(ctx)
    return result(
        summary={
            "enabled": bool(values["enabled"]),
            "latitudeDeg": values["latitude"],
            "longitudeDeg": values["longitude"],
        }
    )


@feature(
    "bim3dAppearance.lightSourceSetup",
    "Light Source Setup",
    part="bim",
    fields=[
        number("azimuth", "Light azimuth", 135.0, unit="°"),
        number("altitude", "Light altitude", 45.0, unit="°", min=-90, max=90),
        number("intensity", "Light intensity", 80.0, unit="%", min=0, max=100),
    ],
)
def light_source_setup(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure the primary view light source."""
    require_bim(ctx)
    return result(
        summary={
            "azimuthDeg": values["azimuth"],
            "altitudeDeg": values["altitude"],
            "intensityPercent": values["intensity"],
        }
    )


@feature(
    "bim3dAppearance.perspectiveCamera",
    "Perspective Camera",
    part="bim",
    fields=[
        number("focalLength", "Camera focal length", 50.0, unit="mm", min=10),
        number("sensorWidth", "Sensor width", 36.0, unit="mm", min=1),
    ],
)
def perspective_camera(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure a perspective camera lens."""
    require_bim(ctx)
    return result(
        summary={"focalLengthMm": values["focalLength"], "sensorWidthMm": values["sensorWidth"]}
    )


@feature(
    "bim3dAppearance.focalLength",
    "Focal Length",
    part="bim",
    fields=[number("focalLength", "Focal length", 50.0, unit="mm", min=10)],
)
def focal_length(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set the 3D camera focal length."""
    require_bim(ctx)
    return result(summary={"focalLengthMm": values["focalLength"]})


@feature(
    "bim3dAppearance.realtimeRaytracing",
    "Realtime Raytracing",
    part="bim",
    fields=[
        checkbox("enabled", "Enable realtime ray tracing", False),
        number("samples", "Ray samples", 4.0, unit="samples", min=1, max=64),
    ],
)
def realtime_raytracing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure realtime ray-tracing preview."""
    require_bim(ctx)
    return result(summary={"enabled": bool(values["enabled"]), "samples": int(values["samples"])})


@feature(
    "bim3dAppearance.visualStyles",
    "Visual Styles",
    part="bim",
    fields=[
        select(
            "style",
            "Visual style",
            [
                ("shaded", "Shaded"),
                ("realistic", "Realistic"),
                ("wireframe", "Wireframe"),
                ("xray", "X-Ray"),
            ],
            "shaded",
        )
    ],
)
def visual_styles(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select a BIM visual style."""
    require_bim(ctx)
    return result(summary={"visualStyle": values["style"]})


@feature(
    "bim3dAppearance.renderRegion",
    "Render Region",
    part="bim",
    fields=[
        number("width", "Region width", 20.0, unit="m", min=0.1),
        number("height", "Region height", 15.0, unit="m", min=0.1),
        checkbox("active", "Render region active", True),
    ],
)
def render_region(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a rectangular render region."""
    require_bim(ctx)
    return result(
        summary={
            "widthM": values["width"],
            "heightM": values["height"],
            "areaM2": values["width"] * values["height"],
            "active": bool(values["active"]),
        }
    )
