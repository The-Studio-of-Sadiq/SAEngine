/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { EditorInputCapabilities, IEditorSerializer, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';

const drawingIcon = registerIcon('saengine-drawing-preview-icon', Codicon.preview, localize('saengineDrawingPreviewIcon', "Icon of the SAEngine drawing sheet preview."));

const DRAWING_PREVIEW_SCHEME = 'saengine-drawing';

/** The sheet a preview shows: its picture, and its DXF and PDF for the hand-off. */
export interface IDrawingPreviewSheet {
	readonly number: string;
	readonly title: string;
	readonly png: URI;
	readonly dxf?: URI;
	readonly pdf?: URI;
	readonly pdfPage?: number;
	readonly size?: string;
	readonly scale?: string;
	readonly stale?: boolean;
	/** The project it belongs to (the preview asks the backend about its staleness). */
	readonly root?: URI;
}

function sameUri(a: URI | undefined, b: URI | undefined): boolean {
	return a?.toString() === b?.toString();
}

/** Whether two sheets show the same (same files, title, size, scale and staleness). */
export function sameSheet(a: IDrawingPreviewSheet, b: IDrawingPreviewSheet): boolean {
	return a.number === b.number && a.title === b.title && sameUri(a.png, b.png) && sameUri(a.dxf, b.dxf) && sameUri(a.pdf, b.pdf)
		&& a.pdfPage === b.pdfPage && a.size === b.size && a.scale === b.scale && !!a.stale === !!b.stale && sameUri(a.root, b.root);
}

/** One generated drawing sheet, shown as its picture with zoom and pan (part 11, Drawings). */
export class DrawingPreviewInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.drawingPreview';
	static readonly EDITOR_ID = 'workbench.editor.saengine.drawingPreview';

	readonly resource: URI;

	private readonly _onDidChangeSheet = this._register(new Emitter<IDrawingPreviewSheet>());
	/** The sheet changed (see {@link update}); its picture may be another file. */
	readonly onDidChangeSheet: Event<IDrawingPreviewSheet> = this._onDidChangeSheet.event;

	constructor(private _sheet: IDrawingPreviewSheet) {
		super();
		this.resource = URI.from({ scheme: DRAWING_PREVIEW_SCHEME, path: _sheet.png.path, query: _sheet.png.scheme });
	}

	get sheet(): IDrawingPreviewSheet {
		return this._sheet;
	}

	/**
	 * The same sheet after a new generation (its title, staleness or files changed). Returns
	 * whether anything changed; an equal sheet changes nothing (and fires nothing).
	 */
	update(sheet: IDrawingPreviewSheet): boolean {
		if (sameSheet(this._sheet, sheet)) {
			return false;
		}
		this._sheet = sheet;
		this._onDidChangeSheet.fire(sheet);
		this._onDidChangeLabel.fire();
		return true;
	}

	override get typeId(): string {
		return DrawingPreviewInput.ID;
	}

	override get editorId(): string {
		return DrawingPreviewInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Readonly;
	}

	override getName(): string {
		return this._sheet.number;
	}

	override getDescription(): string {
		return this._sheet.title;
	}

	override getTitle(): string {
		return localize('drawingPreview.tabTitle', "{0} {1}", this._sheet.number, this._sheet.title);
	}

	override getIcon(): ThemeIcon {
		return drawingIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || (other instanceof DrawingPreviewInput && other.resource.toString() === this.resource.toString());
	}
}

interface ISerializedSheet {
	readonly number: string;
	readonly title: string;
	readonly png: string;
	readonly dxf?: string;
	readonly pdf?: string;
	readonly pdfPage?: number;
	readonly size?: string;
	readonly scale?: string;
	readonly stale?: boolean;
	readonly root?: string;
}

/** Restores a sheet preview with the window (the picture is read again from disk). */
export class DrawingPreviewInputSerializer implements IEditorSerializer {

	canSerialize(): boolean {
		return true;
	}

	serialize(input: DrawingPreviewInput): string {
		const s = input.sheet;
		const data: ISerializedSheet = {
			number: s.number, title: s.title, png: s.png.toString(), dxf: s.dxf?.toString(), pdf: s.pdf?.toString(),
			pdfPage: s.pdfPage, size: s.size, scale: s.scale, stale: s.stale || undefined, root: s.root?.toString(),
		};
		return JSON.stringify(data);
	}

	deserialize(_instantiationService: IInstantiationService, raw: string): DrawingPreviewInput | undefined {
		try {
			const data = JSON.parse(raw) as ISerializedSheet;
			if (typeof data.number !== 'string' || typeof data.png !== 'string') {
				return undefined;
			}
			return new DrawingPreviewInput({
				number: data.number, title: data.title ?? data.number, png: URI.parse(data.png),
				dxf: data.dxf ? URI.parse(data.dxf) : undefined, pdf: data.pdf ? URI.parse(data.pdf) : undefined,
				pdfPage: data.pdfPage, size: data.size, scale: data.scale, stale: data.stale === true,
				root: typeof data.root === 'string' ? URI.parse(data.root) : undefined,
			});
		} catch {
			return undefined;
		}
	}
}
