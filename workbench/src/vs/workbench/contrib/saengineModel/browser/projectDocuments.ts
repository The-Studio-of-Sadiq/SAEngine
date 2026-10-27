/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { RunOnceScheduler } from '../../../../base/common/async.js';
import { Emitter } from '../../../../base/common/event.js';
import { Disposable, DisposableStore } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IEditorService, SIDE_GROUP } from '../../../services/editor/common/editorService.js';
import { ModelSelection } from '../../../services/saengineProject/common/modelSelection.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { IProjectDocuments } from './modelData.js';

/** The part files the views read; a project has the floor plan or the structural model. */
const PARTS = ['floorPlan', 'structure', 'objects', 'materials', 'bim', 'mep'] as const;

/** The grids and stories form for the floor plan (registered by the library editors). */
const GRIDS_EDITOR_ID = 'workbench.editor.saengine.grids';

function parse(model: ITextModel | undefined): unknown {
	try {
		return model ? JSON.parse(model.getValue()) : undefined;
	} catch {
		return undefined;
	}
}

/**
 * The open project's part files as the views read them: the shared text models, so unsaved
 * edits in any editor show up at once. The views never write them.
 */
export class ProjectDocuments extends Disposable {

	private readonly _onDidChange = this._register(new Emitter<void>());
	readonly onDidChange = this._onDidChange.event;

	private readonly references = this._register(new DisposableStore());
	private readonly models = new Map<string, ITextModel>();
	private readonly changeScheduler = this._register(new RunOnceScheduler(() => this._onDidChange.fire(), 150));
	private generation = 0;

	constructor(
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ITextModelService private readonly textModelService: ITextModelService,
	) {
		super();
		this._register(projectService.onDidChangeProject(() => this.track()));
		void this.track();
	}

	get documents(): IProjectDocuments {
		const floorPlan = this.models.get('floorPlan');
		const structure = this.models.get('structure');
		return {
			floorPlan: parse(floorPlan),
			floorPlanText: floorPlan?.getValue(),
			structure: parse(structure),
			structureText: structure?.getValue(),
			objects: parse(this.models.get('objects')),
			materials: parse(this.models.get('materials')),
			bim: parse(this.models.get('bim')),
			mep: parse(this.models.get('mep')),
		};
	}

	private async track(): Promise<void> {
		const generation = ++this.generation;
		this.references.clear();
		this.models.clear();
		const root = this.projectService.project?.root;
		if (root) {
			const store = new DisposableStore();
			for (const id of PARTS.filter(id => this.projectService.parts.some(p => p.id === id))) {
				const resource = partFile(root, id);
				try {
					const reference = await this.textModelService.createModelReference(resource);
					if (generation !== this.generation) {
						reference.dispose();
						store.dispose();
						return;
					}
					store.add(reference);
					const model = reference.object.textEditorModel;
					this.models.set(id, model);
					store.add(model.onDidChangeContent(() => this.changeScheduler.schedule()));
				} catch {
					// A missing part file is restored by the project service; show the rest.
				}
			}
			this.references.add(store);
		}
		this._onDidChange.fire();
	}
}

export function partFile(root: URI, id: string): URI {
	const part = partById(id)!;
	return joinPath(root, part.folder, part.mainFile!);
}

/** Library editor option revealing an entry by id (see the library editor). */
export interface IRevealEntryOptions {
	readonly revealId?: string;
}

/**
 * Opens the editor that owns what `selection` describes: the Floor Plan for members and
 * stories, the Grids & Stories form for grid lines, the Object Types editor for types, and the
 * BIM and MEP editors for theirs.
 */
export async function openOwner(selection: ModelSelection | undefined, part: string | undefined, root: URI | undefined, editorService: IEditorService): Promise<void> {
	if (!root) {
		return;
	}
	const kind = selection?.kind;
	if (kind === 'objectType' || (!kind && part === 'objects')) {
		const options: IEditorOptions & IRevealEntryOptions = { revealId: selection?.kind === 'objectType' ? selection.id : undefined };
		await editorService.openEditor({ resource: partFile(root, 'objects'), options });
	} else if (kind === 'gridLine' || (!kind && part === 'grids')) {
		await editorService.openEditor({ resource: partFile(root, 'floorPlan'), options: { override: GRIDS_EDITOR_ID } }, SIDE_GROUP);
	} else if (part === 'bim' || part === 'mep') {
		await editorService.openEditor({ resource: partFile(root, part) });
	} else if (part === 'structure') {
		await editorService.openEditor({ resource: partFile(root, 'structure') });
	} else {
		await editorService.openEditor({ resource: partFile(root, 'floorPlan') });
	}
}

export const OPEN_OWNER_LABELS = {
	showInFloorPlan: localize('action.showInFloorPlan', "Show in Floor Plan"),
	editGrids: localize('action.editGrids', "Edit in Grids & Stories"),
	editObjectType: localize('action.editObjectType', "Edit in Object Types"),
};
