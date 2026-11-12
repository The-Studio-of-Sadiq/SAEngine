/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { IJSONSchema } from '../../../../base/common/jsonSchema.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { IClipboardService } from '../../../../platform/clipboard/common/clipboardService.js';
import { IDialogService, IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IQuickInputService, IQuickPickItem, IQuickPickSeparator } from '../../../../platform/quickinput/common/quickInput.js';
import { ActionKind, describeFailure, IActionInfo, IActionsOutcome, IActionStep, ISaengineActionsService, readSteps, stepNames } from '../../../services/saengineProject/common/saengineActions.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';

/*
 * The shared editing actions in the Command Palette: run a batch file (the same JSON the command
 * line's `saengine action batch` takes) on the open project, and the catalogue of actions.
 */

const category = localize2('saengine.category', "SAEngine");

export const RUN_ACTIONS_FROM_FILE_COMMAND = 'saengine.actions.runFromFile';
export const SHOW_ACTION_CATALOGUE_COMMAND = 'saengine.actions.showCatalogue';

/** "Placed 12 columns. Set 3 storeys." and the warnings: what a batch did, in a few lines. */
export function describeOutcome(outcome: IActionsOutcome): string {
	const messages = outcome.results.map(r => r.message).filter(m => !!m);
	const warnings = outcome.results.flatMap(r => r.warnings);
	const lines = messages.slice(0, 8);
	if (messages.length > 8) {
		lines.push(localize('actions.moreMessages', "... and {0} more.", messages.length - 8));
	}
	if (warnings.length) {
		lines.push(localize('actions.warnings', "Warnings: {0}", warnings.slice(0, 5).join('; ')));
	}
	return lines.join('\n');
}

/** The parameters of an action, one line each: "storeys (integer, required): number of storeys". */
export function describeParams(schema: IJSONSchema): string[] {
	const required = new Set(schema.required ?? []);
	return Object.entries(schema.properties ?? {}).map(([name, property]) => {
		const type = Array.isArray(property.type) ? property.type.join(' | ') : property.type ?? (property.enum ? property.enum.map(v => JSON.stringify(v)).join(' | ') : property.anyOf ? 'one of several' : 'any');
		const flags = required.has(name) ? localize('actions.required', "required") : localize('actions.optional', "optional");
		return property.description ? `${name} (${type}, ${flags}): ${property.description}` : `${name} (${type}, ${flags})`;
	});
}

/** A step of `info` to start from: its required parameters with their defaults or empty values. */
export function exampleStep(info: IActionInfo): IActionStep {
	const params: { [key: string]: unknown } = {};
	const properties = info.paramsSchema.properties ?? {};
	for (const name of info.paramsSchema.required ?? []) {
		const property = properties[name] ?? {};
		const type = Array.isArray(property.type) ? property.type[0] : property.type;
		params[name] = property.default !== undefined ? property.default
			: property.enum?.length ? property.enum[0]
				: type === 'number' || type === 'integer' ? 0
					: type === 'boolean' ? false
						: type === 'array' ? []
							: type === 'object' ? {}
								: '';
	}
	return { action: info.name, params };
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: RUN_ACTIONS_FROM_FILE_COMMAND,
			title: localize2('saengine.actions.runFromFile', "Run Actions from File..."),
			category,
			f1: true,
		});
	}

	override async run(accessor: ServicesAccessor): Promise<IActionsOutcome | undefined> {
		const actions = accessor.get(ISaengineActionsService);
		const fileDialogs = accessor.get(IFileDialogService);
		const fileService = accessor.get(IFileService);
		const dialogs = accessor.get(IDialogService);
		const notifications = accessor.get(INotificationService);
		const project = accessor.get(ISaengineProjectService).project;

		const picked = await fileDialogs.showOpenDialog({
			title: localize('actions.pickFile', "Run Actions from File"),
			canSelectFiles: true,
			canSelectMany: false,
			filters: [{ name: localize('actions.batchFiles', "Action batches"), extensions: ['json'] }],
			defaultUri: project?.root,
		});
		if (!picked?.length) {
			return undefined;
		}
		let steps: IActionStep[];
		try {
			steps = readSteps(JSON.parse((await fileService.readFile(picked[0])).value.toString()));
		} catch (error) {
			notifications.error(localize('actions.badFile', "{0} is not a batch of actions: {1}", picked[0].fsPath, error instanceof Error ? error.message : String(error)));
			return undefined;
		}
		try {
			if (await actions.needsWrite(steps)) {
				const { confirmed } = await dialogs.confirm({
					message: localize('actions.confirmRun', "Save the project and run {0}?", stepNames(steps)),
					detail: localize('actions.confirmRunDetail', "This batch runs the analysis, the design or an export: SAEngine saves your edited parts first, then writes the results. Edits in the batch are saved with them."),
					primaryButton: localize({ key: 'actions.saveAndRun', comment: ['&& denotes a mnemonic'] }, "&&Save and Run"),
				});
				if (!confirmed) {
					return undefined;
				}
			}
			const outcome = await actions.run(steps, { apply: true });
			if (outcome.ok) {
				notifications.notify({
					severity: outcome.results.some(r => r.warnings.length) ? Severity.Warning : Severity.Info,
					message: localize('actions.done', "Ran {0} action(s). {1}", steps.length, describeOutcome(outcome)),
				});
			} else {
				notifications.error(localize('actions.failed', "Nothing was changed. {0}", describeFailure(steps, outcome)));
			}
			return outcome;
		} catch (error) {
			notifications.error(localize('actions.error', "The actions could not be run: {0}", error instanceof Error ? error.message : String(error)));
			return undefined;
		}
	}
});

interface IActionPick extends IQuickPickItem {
	readonly info: IActionInfo;
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: SHOW_ACTION_CATALOGUE_COMMAND,
			title: localize2('saengine.actions.showCatalogue', "Show Action Catalogue"),
			category,
			f1: true,
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		const actions = accessor.get(ISaengineActionsService);
		const quickInput = accessor.get(IQuickInputService);
		const clipboard = accessor.get(IClipboardService);
		const notifications = accessor.get(INotificationService);

		let catalogue: readonly IActionInfo[];
		try {
			catalogue = await actions.listActions();
		} catch (error) {
			notifications.error(localize('actions.noCatalogue', "The action catalogue could not be read: {0}", error instanceof Error ? error.message : String(error)));
			return;
		}
		const groups: { kind: ActionKind; label: string }[] = [
			{ kind: 'edit', label: localize('actions.kind.edit', "Edit the model") },
			{ kind: 'query', label: localize('actions.kind.query', "Read the project") },
			{ kind: 'run', label: localize('actions.kind.run', "Run, design and export") },
		];
		const items: (IActionPick | IQuickPickSeparator)[] = [];
		for (const group of groups) {
			const infos = catalogue.filter(info => info.kind === group.kind).sort((a, b) => a.name.localeCompare(b.name));
			if (!infos.length) {
				continue;
			}
			items.push({ type: 'separator', label: group.label });
			for (const info of infos) {
				const params = describeParams(info.paramsSchema);
				items.push({
					info,
					label: info.name,
					description: info.summary,
					detail: params.length ? params.join(' · ') : localize('actions.noParams', "No parameters."),
				});
			}
		}
		const picked = await quickInput.pick(items, {
			title: localize('actions.catalogue', "Action Catalogue"),
			placeHolder: localize('actions.cataloguePlaceholder', "The actions the command line, scripts, the app and the AI share. Choose one to copy an example step."),
			matchOnDescription: true,
			matchOnDetail: true,
		});
		if (!picked) {
			return;
		}
		await clipboard.writeText(JSON.stringify([exampleStep(picked.info)], undefined, '\t'));
		notifications.info(localize('actions.copied', "An example step of {0} is on the clipboard: put it in a batch file and run it with Run Actions from File, or with \"saengine action batch\" in a terminal.", picked.info.name));
	}
});
