/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, MenuRegistry, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { CommandsRegistry } from '../../../../platform/commands/common/commands.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { EditorResourceAccessor } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { FEM_RESULT_TABLES_COMMAND, FEM_RUN_CASES_COMMAND, FEM_SHOW_LOG_COMMAND, IFemRunOptions } from '../browser/femResultsBar.js';
import { FemAnalysisRunner } from './femAnalysisRunner.js';
import { CANCEL_RUN_ALL_COMMAND_ID, IRunAllService, RESTART_ENGINE_COMMAND_ID, RUN_ALL_COMMAND_ID, RunAllRunningContext, RunAllService } from './runAll.js';

const category = localize2('saengine.category', "SAEngine");

/** Set by the SAEngine model contribution while a project is open. */
const projectOpen = ContextKeyExpr.has('saengineProjectOpen');

registerSingleton(IRunAllService, RunAllService, InstantiationType.Delayed);

/**
 * Runs the analysis of a model with the progress reported to the caller (the FEM editor's
 * toolbar and status line). Internal: the FEM editor calls it by id.
 */
CommandsRegistry.registerCommand(FEM_RUN_CASES_COMMAND, (accessor, model: URI, options?: IFemRunOptions) =>
	accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).run(model, options));

/** The result tables of a model's last run. Internal: the FEM editor's tables panel calls it by id. */
CommandsRegistry.registerCommand(FEM_RESULT_TABLES_COMMAND, (accessor, model: URI) =>
	accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resultTables(model));

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: CANCEL_RUN_ALL_COMMAND_ID,
			title: localize2('runAll.stop', "Stop Run All"),
			category,
			icon: Codicon.debugStop,
			f1: true,
			precondition: RunAllRunningContext,
		});
	}

	override run(accessor: ServicesAccessor): void {
		accessor.get(IRunAllService).cancel();
	}
});

// While Run All runs, the title bar's Run All becomes Stop (G6).
MenuRegistry.appendMenuItem(MenuId.TitleBar, {
	command: {
		id: CANCEL_RUN_ALL_COMMAND_ID,
		title: localize2('runAll.stopShort', "Stop"),
		tooltip: localize('runAll.stopTooltip', "Stop Run All (the step going is stopped; the engine restarts when it is working on it)"),
		icon: Codicon.debugStop,
	},
	when: ContextKeyExpr.and(projectOpen, RunAllRunningContext),
	group: 'navigation',
	order: -1,
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: RESTART_ENGINE_COMMAND_ID,
			title: localize2('restartEngine', "Restart Engine"),
			category,
			f1: true,
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		const runAll = accessor.get(IRunAllService);
		const notificationService = accessor.get(INotificationService);
		if (runAll.running) {
			runAll.cancel(); // its step's work ends with the engine
		}
		await runAll.restartEngine();
		notificationService.info(localize('restartEngine.done', "The SAEngine engine was stopped; it starts again with the next request."));
	}
});

/** The model of the active editor, or the one given. */
function modelOf(accessor: ServicesAccessor, resource: unknown): URI | undefined {
	const model = URI.isUri(resource) ? resource : EditorResourceAccessor.getOriginalUri(accessor.get(IEditorService).activeEditor);
	return model?.path.toLowerCase().endsWith('.osmodel') ? model : undefined;
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.fem.runSelectedCases',
			title: localize2('femRunSelectedCases', "Run Selected Analysis Cases..."),
			category,
			f1: true,
		});
	}

	override async run(accessor: ServicesAccessor, resource?: URI): Promise<void> {
		const notificationService = accessor.get(INotificationService);
		const runner = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner);
		const model = modelOf(accessor, resource);
		if (!model) {
			notificationService.info(localize('femRunSelectedCases.noModel', "Open an .osmodel file to run its analysis."));
			return;
		}
		await runner.run(model, { pick: true });
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: FEM_SHOW_LOG_COMMAND,
			title: localize2('femShowLog', "Show Analysis Log"),
			category,
			f1: true,
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).showLog();
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: RUN_ALL_COMMAND_ID,
			title: localize2('runAll', "Run All"),
			category,
			icon: Codicon.runAll,
			f1: true,
			precondition: projectOpen,
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(IRunAllService).run();
	}
});
