import { AcDbAttribute, AcDbAttributeDefinition, AcDbBlockReference, AcDbText, AcGeMatrix3d, AcGePoint3d } from '@mlightcad/data-model';

export interface BlockPoint { x: number; y: number; z: number }

/** Applies an INSERT's base-point, scale, rotation and insertion-point transform. */
export function transformBlockPoint(point: BlockPoint, base: BlockPoint, insertion: BlockPoint, sx: number, sy: number, rotation: number): BlockPoint {
	const x = (point.x - base.x) * sx;
	const y = (point.y - base.y) * sy;
	const c = Math.cos(rotation), s = Math.sin(rotation);
	return { x: insertion.x + x * c - y * s, y: insertion.y + x * s + y * c, z: insertion.z + point.z - base.z };
}

export function blockTransform(reference: AcDbBlockReference): AcGeMatrix3d {
	return reference.blockTransform;
}

export function makeAttribute(definition: AcDbAttributeDefinition, value: string): AcDbAttribute {
	const attr = new AcDbAttribute();
	attr.tag = definition.tag;
	attr.textString = value;
	attr.isInvisible = definition.isInvisible;
	attr.isVerifiable = definition.isVerifiable;
	attr.isPreset = definition.isPreset;
	attr.fieldLength = definition.fieldLength;
	attr.lockPositionInBlock = definition.lockPositionInBlock;
	attr.position = definition.position.clone();
	attr.height = definition.height;
	attr.rotation = definition.rotation;
	attr.styleName = definition.styleName;
	return attr;
}

export function attributeAsText(attribute: AcDbAttribute): AcDbText {
	const text = new AcDbText();
	text.textString = attribute.textString;
	text.position = attribute.position.clone();
	text.height = attribute.height;
	text.rotation = attribute.rotation;
	text.styleName = attribute.styleName;
	text.layer = attribute.layer;
	text.color = attribute.color;
	text.lineType = attribute.lineType;
	return text;
}
