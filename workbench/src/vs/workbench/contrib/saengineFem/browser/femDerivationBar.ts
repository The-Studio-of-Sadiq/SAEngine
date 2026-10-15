/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append, clearNode } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable, DisposableStore } from '../../../../base/common/lifecycle.js';
import { dirname, isEqual, joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { sourceStamp } from '../../../services/saengineProject/common/partSources.js';
import { ISaengineProjectService, PROJECT_PARTS } from '../../../services/saengineProject/common/saengineProject.js';

/** Desktop command deriving the analysis model with the Python models (see `saengine.fem.derive`). */
const DERIVE_COMMAND = 'saengine.fem.derive';
const RUN_COMMAND = 'saengine.fem.runAnalysis';

/** The parts the analysis model is derived from, with the names the derivation records them under. */
const SOURCES: readonly { readonly part: string; readonly key: string; readonly label: string }[] = [
	{ part: 'bim', key: 'bim', label: localize('fem.source.bim', "Building Model") },
	{ part: 'settings', key: 'settings', label: localize('fem.source.settings', "Project Settings") },
	{ part: 'objects', key: 'objects', label: localize('fem.source.objects', "Object Types") },
	{ part: 'materials', key: 'materials', label: localize('fem.source.materials', "Materials") },
];

interface IFemDerivation {
	readonly text?: string;
	readonly notes?: readonly string[];
	readonly summary?: { readonly [key: string]: number };
	readonly problems?: readonly string[];
}

function partFile(root: URI, id: string): URI {
	const part = PROJECT_PARTS.find(p => p.id === id)!;
	return joinPath(root, part.folder, part.mainFile!);
}

/** The source stamps recorded in a derived model's description ("Sources: bim=…; settings=…"). */
export function recordedSources(description: unknown): Map<string, string> {
	const sources = new Map<string, string>();
	const match = typeof description === 'string' ? /Sources: (?<list>.*)$/.exec(description) : null;
	for (const entry of match?.groups?.list.split(';') ?? []) {
		const [key, value] = entry.trim().split('=');
		if (key && value) {
			sources.set(key, value);
		}
	}
	return sources;
}

/**
 * Above the project's analysis model (`08 FEM/model.osmodel`): where it comes from, whether its
 * sources have changed since it was derived, and the actions of Part 8 (derive, run).
 * The analysis model is never edited by hand: it is derived again on request.
 */
export class FemDerivationBar extends Disposable {

	private readonly element: HTMLElement;
	private readonly store = this._register(new DisposableStore());
	private readonly buttons = this._register(new DisposableStore());
	private readonly models = new Map<string, ITextModel>();
	private description: unknown;
	private resource: URI | undefined;
	private requested: URI | undefined;
	private deriving = false;

	constructor(
		container: HTMLElement,
		private readonly onDidChangeHeight: () => void,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@ICommandService private readonly commandService: ICommandService,
		@IFileService private readonly fileService: IFileService,
		@INotificationService private readonly notificationService: INotificationService,
	) {
		super();
		this.element = append(container, $('.fem-derivation'));
		// Editors restore before the project is detected: look again once it is.
		this._register(this.projectService.onDidChangeProject(() => void this.setResource(this.requested)));
	}

	/** Shows the bar for `resource` when it is the project's analysis model; hides it otherwise. */
	async setResource(resource: URI | undefined): Promise<void> {
		this.requested = resource;
		this.store.clear();
		this.models.clear();
		const root = this.projectService.project?.root;
		this.resource = root && resource && isEqual(resource, partFile(root, 'fem')) ? resource : undefined;
		if (root && this.resource) {
			for (const { part } of SOURCES) {
				try {
					const reference = await this.textModelService.createModelReference(partFile(root, part));
					this.store.add(reference);
					const model = reference.object.textEditorModel;
					this.models.set(part, model);
					this.store.add(model.onDidChangeContent(() => this.render()));
				} catch {
					// A missing part file shows as changed until it is restored.
				}
			}
		}
		this.render();
	}

	/** The model's description, holding the stamps of the sources it was derived from. */
	setDescription(description: unknown): void {
		this.description = description;
		this.render();
	}

	private render(): void {
		this.buttons.clear();
		clearNode(this.element);
		this.element.classList.toggle('visible', !!this.resource);
		if (!this.resource) {
			this.onDidChangeHeight();
			return;
		}
		const recorded = recordedSources(this.description);
		const changed = SOURCES.filter(({ part, key }) => {
			const model = this.models.get(part);
			return !model || recorded.get(key) !== sourceStamp(model.getValue());
		});
		const status = append(this.element, $('span.fem-derivation-status'));
		if (!recorded.size) {
			append(status, $(`span${ThemeIcon.asCSSSelector(Codicon.info)}`));
			append(status, $('span', undefined, localize('fem.notDerived', "The analysis model has not been derived from the building model yet.")));
		} else if (changed.length) {
			append(status, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`));
			append(status, $('span', undefined, localize('fem.changed', "Changed since the analysis model was derived: {0}.", changed.map(c => c.label).join(', '))));
		} else {
			append(status, $(`span${ThemeIcon.asCSSSelector(Codicon.check)}`));
			append(status, $('span', undefined, localize('fem.current', "Derived from the current building model and project settings.")));
		}
		const actions = append(this.element, $('.fem-derivation-actions'));
		const derive = this.buttons.add(new Button(actions, { ...defaultButtonStyles, secondary: !changed.length && !!recorded.size, supportIcons: true }));
		derive.label = `$(${Codicon.refresh.id}) ${recorded.size ? localize('fem.deriveAgain', "Derive Again") : localize('fem.derive', "Derive from Building Model")}`;
		derive.enabled = !this.deriving;
		this.buttons.add(derive.onDidClick(() => this.derive()));
		if (recorded.size) {
			const run = this.buttons.add(new Button(actions, { ...defaultButtonStyles, secondary: !!changed.length, supportIcons: true }));
			run.label = `$(${Codicon.play.id}) ${localize('fem.run', "Run Analysis")}`;
			this.buttons.add(run.onDidClick(() => this.commandService.executeCommand(RUN_COMMAND, this.resource)));
		}
		this.onDidChangeHeight();
	}

	private async derive(): Promise<void> {
		const resource = this.resource;
		const text = (part: string) => this.models.get(part)?.getValue();
		const [bimText, settingsText, objectsText, materialsText] = SOURCES.map(s => text(s.part));
		if (!resource || bimText === undefined || settingsText === undefined || objectsText === undefined || materialsText === undefined) {
			return;
		}
		this.deriving = true;
		this.render();
		try {
			const result = await this.commandService.executeCommand<IFemDerivation>(DERIVE_COMMAND, { bimText, objectsText, materialsText, settingsText, modelFolder: dirname(resource).fsPath });
			if (!result?.text) {
				this.notificationService.warn(localize('fem.deriveProblems', "The analysis model could not be derived: {0}", (result?.problems ?? []).join('; ')));
				return;
			}
			await this.fileService.writeFile(resource, VSBuffer.fromString(result.text));
			const summary = result.summary ?? {};
			const facts = localize('fem.derived', "Derived {0} nodes and {1} elements; base shear {2} kN, seismic weight {3} kN.",
				summary.nodes ?? 0, summary.elements ?? 0, (summary.base_shear_kN ?? 0).toFixed(1), (summary.weight_kN ?? 0).toFixed(1));
			this.notificationService.notify({
				severity: result.notes?.length ? Severity.Warning : Severity.Info,
				message: result.notes?.length ? `${facts} ${localize('fem.notes', "Notes: {0}", result.notes.join('; '))}` : facts,
			});
		} catch (error) {
			this.notificationService.error(localize('fem.deriveFailed', "The analysis model could not be derived: {0}", String(error)));
		} finally {
			this.deriving = false;
			this.render();
		}
	}
}
