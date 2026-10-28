/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { isEqual } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { EditorInputCapabilities, GroupIdentifier, IEditorSerializer, IRevertOptions, ISaveOptions, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';

const architectureIcon = registerIcon('saengine-architecture-editor-icon', Codicon.home, localize('architectureEditorIcon', "Icon of the architecture editor."));

/**
 * The project's architecture (`05 Floor Plan/architecture.json`): walls, doors, windows and
 * rooms drawn on the floor plan's grids, one story at a time. The file is a JSON text model, so
 * unsaved changes, Save, Revert and backups are those of the text file.
 */
export class ArchitectureEditorInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.architecture';
	static readonly EDITOR_ID = 'workbench.editor.saengine.architecture';

	/** Story shown, kept while the input lives so switching tabs returns to it. */
	story: string | undefined;

	constructor(
		readonly resource: URI,
		@ITextFileService private readonly textFileService: ITextFileService,
	) {
		super();
		this._register(this.textFileService.files.onDidChangeDirty(model => {
			if (isEqual(model.resource, this.resource)) {
				this._onDidChangeDirty.fire();
			}
		}));
	}

	override get typeId(): string {
		return ArchitectureEditorInput.ID;
	}

	override get editorId(): string {
		return ArchitectureEditorInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.None;
	}

	override getName(): string {
		return localize('architecture', "Architecture");
	}

	override getIcon(): ThemeIcon {
		return architectureIcon;
	}

	override isDirty(): boolean {
		return this.textFileService.isDirty(this.resource);
	}

	override async save(_group: GroupIdentifier, options?: ISaveOptions): Promise<EditorInput | IUntypedEditorInput | undefined> {
		const saved = await this.textFileService.save(this.resource, options);
		return saved ? this : undefined;
	}

	override async revert(_group: GroupIdentifier, options?: IRevertOptions): Promise<void> {
		await this.textFileService.revert(this.resource, options);
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || (other instanceof ArchitectureEditorInput && isEqual(other.resource, this.resource));
	}

	override toUntyped(): IUntypedEditorInput {
		return { resource: this.resource, options: { override: ArchitectureEditorInput.EDITOR_ID } };
	}
}

export class ArchitectureEditorInputSerializer implements IEditorSerializer {

	canSerialize(): boolean {
		return true;
	}

	serialize(editor: ArchitectureEditorInput): string {
		return JSON.stringify({ resource: editor.resource.toJSON(), story: editor.story });
	}

	deserialize(instantiationService: IInstantiationService, serialized: string): ArchitectureEditorInput {
		const data = JSON.parse(serialized);
		const input = instantiationService.createInstance(ArchitectureEditorInput, URI.revive(data.resource));
		input.story = typeof data.story === 'string' ? data.story : undefined;
		return input;
	}
}
