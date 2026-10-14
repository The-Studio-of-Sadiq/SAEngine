/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { dirname, isEqual, joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
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

/**
 * The project's floor plan (`05 Floor Plan/floor-plan.json`): a plan view, one story at a
 * time, of the building model in `06 BIM/bim.json`, where members are placed. What the plan
 * edits is the building model, so its unsaved changes, Save and Revert are those of `bim.json`.
 */
export class FloorPlanEditorInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.floorPlan';
	static readonly EDITOR_ID = 'workbench.editor.saengine.floorPlan';

	/** The building model the plan shows and edits. */
	readonly bimResource: URI;

	/** Story shown, kept while the input lives so switching tabs returns to it. */
	story: string | undefined;

	constructor(
		readonly resource: URI,
		@ITextFileService private readonly textFileService: ITextFileService,
	) {
		super();
		this.bimResource = siblingPartFile(resource, 'bim');
		this._register(this.textFileService.files.onDidChangeDirty(model => {
			if (isEqual(model.resource, this.bimResource)) {
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

	override isDirty(): boolean {
		return this.textFileService.isDirty(this.bimResource);
	}

	override async save(_group: GroupIdentifier, options?: ISaveOptions): Promise<EditorInput | IUntypedEditorInput | undefined> {
		await this.textFileService.save(this.bimResource, options);
		return this;
	}

	override async revert(_group: GroupIdentifier, options?: IRevertOptions): Promise<void> {
		await this.textFileService.revert(this.bimResource, options);
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
