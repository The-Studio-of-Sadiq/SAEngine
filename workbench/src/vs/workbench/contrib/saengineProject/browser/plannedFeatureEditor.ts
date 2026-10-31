/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/saengineTokens.css';
import './media/plannedFeature.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType } from '../../../../base/browser/dom.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { DisposableStore, IDisposable } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { onDidChangePlannedFeatures, plannedFeature } from '../../../services/saengineProject/common/plannedFeatures.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { PlannedFeatureInput } from './plannedFeatureInput.js';
import { partName } from './projectParts.js';

/** Command that opens a planned feature's page; its argument is the feature id. */
export const OPEN_PLANNED_FEATURE_COMMAND = 'saengine.openPlannedFeature';

/**
 * The page of a feature this MVP shows but does not compute yet: a "Planned" badge, the part
 * that will hold it, what it will do, the planned steps, a disabled preview of its inputs,
 * what it will produce and the references it will follow. It never shows numbers of its own.
 */
export class PlannedFeatureEditor extends EditorPane {

	static readonly ID = PlannedFeatureInput.EDITOR_ID;

	private container!: HTMLElement;

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
	) {
		super(PlannedFeatureEditor.ID, group, telemetryService, themeService, storageService);
		this._register(onDidChangePlannedFeatures(() => this.render()));
	}

	protected createEditor(parent: HTMLElement): void {
		this.container = append(parent, $('.saengine-planned', { tabIndex: -1 }));
	}

	override async setInput(input: PlannedFeatureInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.render();
	}

	override layout(dimension: Dimension): void {
		this.container.style.width = `${dimension.width}px`;
		this.container.style.height = `${dimension.height}px`;
	}

	override focus(): void {
		super.focus();
		this.container.focus();
	}

	private render(): void {
		const input = this.input as PlannedFeatureInput | undefined;
		if (!input || !this.container) {
			return;
		}
		clearNode(this.container);
		const page = append(this.container, $('.page'));
		const feature = plannedFeature(input.featureId);
		append(page, $('span.badge', undefined, localize('plannedFeature.badge', "Planned · Not in This MVP")));
		if (!feature) {
			append(page, $('h1', undefined, localize('plannedFeature.unknown', "Planned Feature")));
			append(page, $('p.summary', undefined, localize('plannedFeature.gone', "This planned feature is no longer listed. It may have arrived in this version.")));
			return;
		}
		append(page, $('h1', undefined, feature.title));
		const part = partById(feature.part);
		if (part) {
			const index = this.projectService.parts.findIndex(p => p.id === feature.part);
			const where = index >= 0 ? localize('plannedFeature.partNumbered', "Will live in {0} {1}", index + 1, partName(part)) : localize('plannedFeature.part', "Will live in {0}", partName(part));
			append(page, $('p.part', undefined, where));
		}
		append(page, $('p.summary', undefined, feature.summary));

		if (feature.steps?.length) {
			append(page, $('h2', undefined, localize('plannedFeature.steps', "How It Will Work")));
			const list = append(page, $('ol'));
			for (const step of feature.steps) {
				append(list, $('li', undefined, step));
			}
		}
		if (feature.inputs?.length) {
			append(page, $('h2', undefined, localize('plannedFeature.inputs', "Inputs (Preview)")));
			const form = append(page, $('.form', { 'aria-disabled': 'true' }));
			for (const field of feature.inputs) {
				const row = append(form, $('label.row'));
				append(row, $('span.label', undefined, field.label));
				const box = append(row, $<HTMLInputElement>('input', { type: 'text', disabled: '', placeholder: field.example ?? '' }));
				box.setAttribute('aria-label', field.label);
				append(row, $('span.unit', undefined, field.unit ?? ''));
			}
		}
		if (feature.outputs?.length) {
			append(page, $('h2', undefined, localize('plannedFeature.outputs', "What It Will Produce")));
			const list = append(page, $('ul'));
			for (const output of feature.outputs) {
				append(list, $('li', undefined, output));
			}
		}
		if (feature.references?.length) {
			append(page, $('h2', undefined, localize('plannedFeature.references', "References")));
			const list = append(page, $('ul.references'));
			for (const reference of feature.references) {
				append(list, $('li', undefined, reference));
			}
		}
		append(page, $('p.note', undefined, localize('plannedFeature.note', "SAEngine is an MVP built on BNBC 2020. This feature is shown so you can see where it will go; it does not compute anything yet.")));
	}
}

/**
 * A small "Planned" chip that opens a planned feature's page, for the place in a part's panel
 * where the feature will appear. The caller registers the returned disposable.
 */
export function appendPlannedFeatureChip(parent: HTMLElement, featureId: string, commandService: ICommandService): IDisposable {
	const store = new DisposableStore();
	const feature = plannedFeature(featureId);
	const title = feature?.title ?? featureId;
	const chip = append(parent, $<HTMLButtonElement>('button.saengine-planned-chip', { type: 'button' }));
	append(chip, $('span.title', undefined, title));
	append(chip, $('span.tag', undefined, localize('plannedFeature.chipTag', "Planned")));
	chip.title = localize('plannedFeature.chipTooltip', "{0} is planned and not in this MVP. Click to see what it will do.", title);
	store.add(addDisposableListener(chip, EventType.CLICK, () => commandService.executeCommand(OPEN_PLANNED_FEATURE_COMMAND, featureId)));
	store.add({ dispose: () => chip.remove() });
	return store;
}
