/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Emitter } from '../../../../base/common/event.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { IActiveStoryChange, IModelSelectionChange, ISaengineModelSelectionService, ModelSelection, sameSelection } from '../common/modelSelection.js';

export class SaengineModelSelectionService extends Disposable implements ISaengineModelSelectionService {

	declare readonly _serviceBrand: undefined;

	private _selection: ModelSelection | undefined;

	private readonly _onDidChangeSelection = this._register(new Emitter<IModelSelectionChange>());
	readonly onDidChangeSelection = this._onDidChangeSelection.event;

	private _activeStory: string | undefined;

	private readonly _onDidChangeActiveStory = this._register(new Emitter<IActiveStoryChange>());
	readonly onDidChangeActiveStory = this._onDidChangeActiveStory.event;

	get selection(): ModelSelection | undefined {
		return this._selection;
	}

	setSelection(selection: ModelSelection | undefined, source: string): void {
		if (!sameSelection(selection, this._selection)) {
			this._selection = selection;
			this._onDidChangeSelection.fire({ selection, source });
		}
	}

	get activeStory(): string | undefined {
		return this._activeStory;
	}

	setActiveStory(story: string | undefined, source: string): void {
		if (story !== this._activeStory) {
			this._activeStory = story;
			this._onDidChangeActiveStory.fire({ story, source });
		}
	}
}

registerSingleton(ISaengineModelSelectionService, SaengineModelSelectionService, InstantiationType.Delayed);
