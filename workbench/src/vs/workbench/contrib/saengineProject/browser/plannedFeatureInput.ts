/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { EditorInputCapabilities, IEditorSerializer, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { plannedFeature } from '../../../services/saengineProject/common/plannedFeatures.js';

const plannedFeatureIcon = registerIcon('saengine-planned-feature-icon', Codicon.beaker, localize('saenginePlannedFeatureIcon', "Icon of a SAEngine feature that is planned but not in this version."));

const PLANNED_FEATURE_SCHEME = 'saengine-planned';

/** The page of one planned feature (see `IPlannedFeature`); one editor per feature. */
export class PlannedFeatureInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.plannedFeature';
	static readonly EDITOR_ID = 'workbench.editor.saengine.plannedFeature';

	readonly resource: URI;

	constructor(readonly featureId: string) {
		super();
		this.resource = URI.from({ scheme: PLANNED_FEATURE_SCHEME, path: `/${featureId}` });
	}

	override get typeId(): string {
		return PlannedFeatureInput.ID;
	}

	override get editorId(): string {
		return PlannedFeatureInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Readonly | EditorInputCapabilities.Singleton;
	}

	override getName(): string {
		return plannedFeature(this.featureId)?.title ?? localize('plannedFeature.unknown', "Planned Feature");
	}

	override getIcon(): ThemeIcon {
		return plannedFeatureIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || (other instanceof PlannedFeatureInput && other.featureId === this.featureId);
	}
}

export class PlannedFeatureInputSerializer implements IEditorSerializer {

	canSerialize(): boolean {
		return true;
	}

	serialize(editor: PlannedFeatureInput): string {
		return editor.featureId;
	}

	deserialize(_instantiationService: IInstantiationService, serialized: string): PlannedFeatureInput {
		return new PlannedFeatureInput(serialized);
	}
}
