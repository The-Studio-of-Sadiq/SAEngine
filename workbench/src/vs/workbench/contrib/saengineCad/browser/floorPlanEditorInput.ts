/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { VSBuffer } from '../../../../base/common/buffer.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { dirname, isEqual, joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { EditorInputCapabilities, GroupIdentifier, IEditorSerializer, IRevertOptions, ISaveOptions, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { PROJECT_PARTS } from '../../../services/saengineProject/common/saengineProject.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';

const floorPlanIcon = registerIcon('saengine-floor-plan-editor-icon', Codicon.symbolArray, localize('floorPlanEditorIcon', "Icon of the floor plan editor."));

/** The main file of project part `id`, in the project whose part file is `resource`. */
export function siblingPartFile(resource: URI, id: string): URI {
	const part = PROJECT_PARTS.find(p => p.id === id)!;
	return joinPath(dirname(dirname(resource)), part.folder, part.mainFile!);
}

/** The drafting DXF file for `storyId`, in `05 Floor Plan/drafting/<storyId>.dxf` of the project containing `resource`. */
export function storyDraftingFile(resource: URI, storyId: string): URI {
	return joinPath(dirname(dirname(resource)), '05 Floor Plan', 'drafting', `${storyId}.dxf`);
}

/** Provides the drawing's current DXF text for the active story; set by the editor pane. */
export interface IFloorPlanDraftingSource {
	toDxf(): string;
	story(): string | undefined;
	reload?(): Promise<void>;
}

/**
 * The project's floor plan (`05 Floor Plan/floor-plan.json`) in its plan view: grids, stories
 * and the members placed on them, one story at a time. The file is a JSON text model, so
 * unsaved changes, Save, Revert and backups are those of the text file.
 */
export class FloorPlanEditorInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.floorPlan';
	static readonly EDITOR_ID = 'workbench.editor.saengine.floorPlan';

	private _story: string | undefined;

	private readonly _onDidChangeStory = this._register(new Emitter<string | undefined>());
	/** The story shown changed (the Tables follow it). */
	readonly onDidChangeStory: Event<string | undefined> = this._onDidChangeStory.event;

	/** Set while shown in the editor pane to access the current storey's live DXF text. */
	draftingSource: IFloorPlanDraftingSource | undefined;
	private readonly draftingDxfs = new Map<string, string>();
	private readonly dirtyDraftingStories = new Set<string>();

	/** Story shown, kept while the input lives so switching tabs returns to it. */
	get story(): string | undefined {
		return this._story;
	}

	set story(story: string | undefined) {
		if (story !== this._story) {
			this._story = story;
			this._onDidChangeStory.fire(story);
		}
	}

	constructor(
		readonly resource: URI,
		@ITextFileService private readonly textFileService: ITextFileService,
		@IFileService private readonly fileService: IFileService,
	) {
		super();
		this._register(this.textFileService.files.onDidChangeDirty(model => {
			if (isEqual(model.resource, this.resource)) {
				this._onDidChangeDirty.fire();
			}
		}));
	}

	override get typeId(): string {
		return FloorPlanEditorInput.ID;
	}

	override get editorId(): string {
		return FloorPlanEditorInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.None;
	}

	override getName(): string {
		return localize('floorPlan', "Floor Plan");
	}

	override getIcon(): ThemeIcon {
		return floorPlanIcon;
	}

	getDraftingDxf(storyId: string): string | undefined {
		return this.draftingDxfs.get(storyId);
	}

	setDraftingDxf(storyId: string, dxf: string, dirty?: boolean): void {
		this.draftingDxfs.set(storyId, dxf);
		if (dirty !== undefined) {
			this.setDraftingDirty(storyId, dirty);
		}
	}

	setDraftingDirty(storyId: string, dirty: boolean): void {
		const wasDirty = this.isDirty();
		if (dirty) {
			this.dirtyDraftingStories.add(storyId);
		} else {
			this.dirtyDraftingStories.delete(storyId);
		}
		if (this.isDirty() !== wasDirty) {
			this._onDidChangeDirty.fire();
		}
	}

	isDraftingDirty(storyId: string): boolean {
		return this.dirtyDraftingStories.has(storyId);
	}

	override isDirty(): boolean {
		return this.textFileService.isDirty(this.resource) || this.dirtyDraftingStories.size > 0;
	}

	override async save(group: GroupIdentifier, options?: ISaveOptions): Promise<EditorInput | IUntypedEditorInput | undefined> {
		if (this.draftingSource) {
			const activeStory = this.draftingSource.story();
			if (activeStory && this.dirtyDraftingStories.has(activeStory)) {
				this.draftingDxfs.set(activeStory, this.draftingSource.toDxf());
			}
		}
		let textSaved = true;
		if (this.textFileService.isDirty(this.resource)) {
			textSaved = !!(await this.textFileService.save(this.resource, options));
		}
		for (const storyId of [...this.dirtyDraftingStories]) {
			const dxf = this.draftingDxfs.get(storyId);
			if (dxf !== undefined) {
				const file = storyDraftingFile(this.resource, storyId);
				await this.fileService.writeFile(file, VSBuffer.fromString(dxf));
				this.dirtyDraftingStories.delete(storyId);
			}
		}
		this._onDidChangeDirty.fire();
		return textSaved ? this : undefined;
	}

	override async revert(group: GroupIdentifier, options?: IRevertOptions): Promise<void> {
		this.dirtyDraftingStories.clear();
		this.draftingDxfs.clear();
		await this.textFileService.revert(this.resource, options);
		await this.draftingSource?.reload?.();
		this._onDidChangeDirty.fire();
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || (other instanceof FloorPlanEditorInput && isEqual(other.resource, this.resource));
	}

	override toUntyped(): IUntypedEditorInput {
		return { resource: this.resource, options: { override: FloorPlanEditorInput.EDITOR_ID } };
	}
}

export class FloorPlanEditorInputSerializer implements IEditorSerializer {

	canSerialize(): boolean {
		return true;
	}

	serialize(editor: FloorPlanEditorInput): string {
		return JSON.stringify({ resource: editor.resource.toJSON(), story: editor.story });
	}

	deserialize(instantiationService: IInstantiationService, serialized: string): FloorPlanEditorInput {
		const data = JSON.parse(serialized);
		const input = instantiationService.createInstance(FloorPlanEditorInput, URI.revive(data.resource));
		input.story = typeof data.story === 'string' ? data.story : undefined;
		return input;
	}
}
