"""BIM 3D presentation and rendering feature buttons."""

from __future__ import annotations

from typing import Any

from saengine.features import FeatureContext, checkbox, feature, number, result, select, text
from saengine.features.bim_common import require_bim, write_bim_json


@feature(
    "bimView.perspectiveView",
    "Perspective View",
    part="bim",
    fields=[
        number("focalLength", "Focal length", 50.0, unit="mm", min=10),
        checkbox("keepTarget", "Keep pivot point", True),
    ],
)
def perspective_view(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Switch the 3D camera to perspective projection."""
    require_bim(ctx)
    return result(
        summary={"focalLengthMm": values["focalLength"], "keepTarget": bool(values["keepTarget"])},
        notes=["Perspective projection uses the entered camera focal length."],
    )


@feature(
    "bimView.orthographicView",
    "Orthographic View",
    part="bim",
    fields=[
        select(
            "axis",
            "Principal axis",
            [("iso", "Isometric"), ("north", "North"), ("east", "East"), ("top", "Top")],
            "iso",
        ),
        checkbox("scaleLock", "Lock scale", True),
    ],
)
def orthographic_view(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Switch the 3D camera to orthographic projection."""
    require_bim(ctx)
    return result(summary={"axis": values["axis"], "scaleLocked": bool(values["scaleLock"])})


@feature(
    "bimView.fieldOfView",
    "Field of View",
    part="bim",
    fields=[number("degrees", "Horizontal field of view", 60.0, unit="°", min=10, max=120)],
)
def field_of_view(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set the horizontal camera field of view."""
    require_bim(ctx)
    return result(summary={"fieldOfViewDeg": values["degrees"]})


@feature(
    "bimView.sunPosition",
    "Sun Position",
    part="bim",
    fields=[
        number("azimuth", "Sun azimuth", 135.0, unit="°"),
        number("altitude", "Sun altitude", 45.0, unit="°", min=-90, max=90),
    ],
)
def sun_position(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set sun azimuth and altitude for the view."""
    require_bim(ctx)
    return result(
        summary={"sunAzimuthDeg": values["azimuth"], "sunAltitudeDeg": values["altitude"]}
    )


@feature(
    "bimView.shadows",
    "Shadows",
    part="bim",
    fields=[
        checkbox("cast", "Cast shadows", True),
        number("softness", "Shadow softness", 20.0, unit="%", min=0, max=100),
    ],
)
def bim_view_shadows(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Toggle cast shadows and their softness."""
    require_bim(ctx)
    return result(
        summary={"castShadows": bool(values["cast"]), "softnessPercent": values["softness"]}
    )


@feature(
    "bimView.ambientLight",
    "Ambient Light",
    part="bim",
    fields=[
        number("ambient", "Ambient light", 40.0, unit="%", min=0, max=100),
        number("direct", "Direct light", 60.0, unit="%", min=0, max=100),
    ],
)
def ambient_light(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Balance ambient and direct lighting levels."""
    require_bim(ctx)
    return result(summary={"ambientPercent": values["ambient"], "directPercent": values["direct"]})


@feature(
    "bimView.quickRender",
    "Quick Render",
    part="bim",
    fields=[
        select(
            "quality",
            "Preview quality",
            [("draft", "Draft"), ("preview", "Preview"), ("good", "Good")],
            "preview",
        ),
        number("samples", "Render samples", 32.0, unit="samples", min=1),
    ],
)
def quick_render(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure a preview-quality render."""
    require_bim(ctx)
    return result(
        summary={"quality": values["quality"], "samples": values["samples"]},
        notes=["Quick render settings apply only to the preview output."],
    )


@feature(
    "bimView.renderSettings",
    "Render Settings",
    part="bim",
    fields=[
        select(
            "resolution",
            "Resolution",
            [("1080p", "1920 x 1080"), ("1440p", "2560 x 1440"), ("4k", "3840 x 2160")],
            "1080p",
        ),
        select(
            "background",
            "Background",
            [("sky", "Sky"), ("white", "White"), ("transparent", "Transparent")],
            "sky",
        ),
        select("quality", "Quality", [("preview", "Preview"), ("high", "High")], "high"),
    ],
)
def render_settings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set render resolution, quality and background."""
    require_bim(ctx)
    return result(
        summary={
            "resolution": values["resolution"],
            "background": values["background"],
            "quality": values["quality"],
        }
    )


@feature(
    "bimView.exportImage",
    "Export Image",
    part="bim",
    fields=[
        select("format", "Image format", [("png", "PNG"), ("jpg", "JPG")], "png"),
        select(
            "resolution",
            "Output resolution",
            [("1080p", "1920 x 1080"), ("1440p", "2560 x 1440"), ("4k", "3840 x 2160")],
            "1080p",
        ),
    ],
)
def export_image(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute camera frustum, pixel dimensions, and BIM model bounding extents for view capture."""
    from saengine.features.bim_common import element_extent

    data = require_bim(ctx)
    dims = {"1080p": (1920, 1080), "1440p": (2560, 1440), "4k": (3840, 2160)}[values["resolution"]]
    w_px, h_px = dims
    aspect = round(w_px / h_px, 3)
    ext = element_extent(data)
    xmin, ymin, xmax, ymax = ext["minXMm"], ext["minYMm"], ext["maxXMm"], ext["maxYMm"]
    dx_m = round((xmax - xmin) / 1000.0, 2)
    dy_m = round((ymax - ymin) / 1000.0, 2)
    megapixels = round((w_px * h_px) / 1e6, 2)
    payload = {
        "format": values["format"],
        "widthPx": w_px,
        "heightPx": h_px,
        "aspectRatio": aspect,
        "megapixels": megapixels,
        "modelSpanXM": dx_m,
        "modelSpanYM": dy_m,
        "elementCount": len(data.get("elements") or []),
    }
    path = write_bim_json(ctx, "bim_view_export_spec.json", payload)
    return result(
        summary={**payload, "exportPath": path},
        notes=[
            f"Computed {w_px}x{h_px} ({megapixels} MP) viewport framing {dx_m}x{dy_m} m model -> {path}."
        ],
    )


@feature(
    "bimView.targetPoint",
    "Target Point",
    part="bim",
    fields=[
        number("x", "Target X", 6500.0, unit="mm"),
        number("y", "Target Y", 2500.0, unit="mm"),
        number("z", "Target Z", 3200.0, unit="mm"),
    ],
)
def target_point(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set the 3D camera pivot."""
    require_bim(ctx)
    return result(
        summary={"targetXMm": values["x"], "targetYMm": values["y"], "targetZMm": values["z"]}
    )


@feature(
    "bimView.lensShift",
    "Lens Shift",
    part="bim",
    fields=[
        number("horizontal", "Horizontal lens shift", 0.0, unit="%"),
        number("vertical", "Vertical lens shift", 0.0, unit="%"),
    ],
)
def lens_shift(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set vertical and horizontal lens shift."""
    require_bim(ctx)
    return result(
        summary={"horizontalPercent": values["horizontal"], "verticalPercent": values["vertical"]}
    )


@feature(
    "bimView.depthOfField",
    "Depth of Field",
    part="bim",
    fields=[
        checkbox("enabled", "Enable depth of field", False),
        number("focusDistance", "Focus distance", 20.0, unit="m", min=0.1),
        number("aperture", "Aperture", 8.0, unit="f", min=1),
    ],
)
def depth_of_field(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure camera depth of field."""
    require_bim(ctx)
    return result(
        summary={
            "enabled": bool(values["enabled"]),
            "focusDistanceM": values["focusDistance"],
            "aperture": values["aperture"],
        }
    )


@feature(
    "bimView.clippingDistance",
    "Clipping Distance",
    part="bim",
    fields=[
        number("near", "Near clipping distance", 0.1, unit="m", min=0.001),
        number("far", "Far clipping distance", 1000.0, unit="m", min=0.1),
    ],
)
def clipping_distance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set near and far camera clipping distances."""
    require_bim(ctx)
    if values["far"] <= values["near"]:
        from saengine.features import FeatureInputError

        raise FeatureInputError(
            "Far clipping distance must be greater than near clipping distance."
        )
    return result(summary={"nearClipM": values["near"], "farClipM": values["far"]})


@feature(
    "bimView.cameraHeight",
    "Camera Height",
    part="bim",
    fields=[number("height", "Camera height", 1.6, unit="m", min=0)],
)
def camera_height(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set the camera eye height."""
    require_bim(ctx)
    return result(summary={"cameraHeightM": values["height"]})


@feature(
    "bimView.skyModel",
    "Sky Model",
    part="bim",
    fields=[
        select(
            "model",
            "Sky model",
            [("clear", "Clear"), ("overcast", "Overcast"), ("partlyCloudy", "Partly cloudy")],
            "clear",
        ),
        number("turbidity", "Atmospheric turbidity", 3.0, unit="", min=1),
    ],
)
def sky_model(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure the sky model used by the render."""
    require_bim(ctx)
    return result(summary={"skyModel": values["model"], "turbidity": values["turbidity"]})


@feature(
    "bimView.fogEffect",
    "Fog Effect",
    part="bim",
    fields=[
        checkbox("enabled", "Enable fog", False),
        number("density", "Fog density", 5.0, unit="%", min=0, max=100),
    ],
)
def fog_effect(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure atmospheric fog."""
    require_bim(ctx)
    return result(summary={"enabled": bool(values["enabled"]), "densityPercent": values["density"]})


@feature(
    "bimView.backdropImage",
    "Backdrop Image",
    part="bim",
    fields=[
        text("imagePath", "Backdrop image path", ""),
        checkbox("stretch", "Stretch to frame", True),
    ],
)
def backdrop_image(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set a backdrop image for the presentation view."""
    require_bim(ctx)
    path = str(values["imagePath"]).strip()
    return result(
        summary={"imagePath": path, "stretch": bool(values["stretch"])},
        notes=[
            "The image path is reported for the renderer; no image is embedded by this feature."
        ],
    )


@feature(
    "bimView.exposureControl",
    "Exposure Control",
    part="bim",
    fields=[
        number("exposure", "Exposure", 0.0, unit="EV"),
        number("gamma", "Display gamma", 2.2, unit="", min=0.1),
    ],
)
def exposure_control(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set render exposure and display gamma."""
    require_bim(ctx)
    return result(summary={"exposureEV": values["exposure"], "gamma": values["gamma"]})


@feature(
    "bimView.ruleOfThirds",
    "Rule of Thirds",
    part="bim",
    fields=[
        checkbox("showGrid", "Show composition grid", True),
        select(
            "grid",
            "Grid style",
            [("thirds", "Rule of thirds"), ("golden", "Golden section")],
            "thirds",
        ),
    ],
)
def rule_of_thirds(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure an image-composition guide."""
    require_bim(ctx)
    return result(summary={"showGrid": bool(values["showGrid"]), "gridStyle": values["grid"]})


@feature(
    "bimView.aspectRatio",
    "Aspect Ratio",
    part="bim",
    fields=[
        select(
            "ratio",
            "Aspect ratio",
            [("16:9", "16:9"), ("4:3", "4:3"), ("1:1", "1:1"), ("3:2", "3:2")],
            "16:9",
        )
    ],
)
def aspect_ratio(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set the presentation aspect ratio."""
    require_bim(ctx)
    return result(summary={"aspectRatio": values["ratio"]})


@feature(
    "bimView.watermark",
    "Watermark",
    part="bim",
    fields=[
        text("text", "Watermark text", "SAEngine"),
        select(
            "position",
            "Position",
            [
                ("topLeft", "Top left"),
                ("topRight", "Top right"),
                ("bottomLeft", "Bottom left"),
                ("bottomRight", "Bottom right"),
            ],
            "bottomRight",
        ),
        number("opacity", "Opacity", 30.0, unit="%", min=0, max=100),
    ],
)
def watermark(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure an exported-view watermark."""
    require_bim(ctx)
    return result(
        summary={
            "watermarkText": values["text"],
            "position": values["position"],
            "opacityPercent": values["opacity"],
        }
    )


@feature(
    "bimView.frameBorder",
    "Frame Border",
    part="bim",
    fields=[
        checkbox("enabled", "Draw border", True),
        number("width", "Border width", 2.0, unit="px", min=0.5, max=20),
        select(
            "colour",
            "Border colour",
            [("black", "Black"), ("white", "White"), ("grey", "Grey")],
            "black",
        ),
    ],
)
def frame_border(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure an exported-view frame border."""
    require_bim(ctx)
    return result(
        summary={
            "enabled": bool(values["enabled"]),
            "widthPx": values["width"],
            "colour": values["colour"],
        }
    )


@feature(
    "bimView.captionText",
    "Caption Text",
    part="bim",
    fields=[
        text("caption", "Caption", ""),
        select("position", "Caption position", [("top", "Top"), ("bottom", "Bottom")], "bottom"),
    ],
)
def caption_text(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set presentation caption text and position."""
    require_bim(ctx)
    return result(summary={"caption": values["caption"], "position": values["position"]})
