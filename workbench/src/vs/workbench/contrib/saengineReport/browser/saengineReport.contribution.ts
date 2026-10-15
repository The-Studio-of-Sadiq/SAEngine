/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IProgressService, ProgressLocation } from '../../../../platform/progress/common/progress.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { BUILD_REPORT_COMMAND_ID, IReportBuildRequest, IReportBuildResult, reportProblems, reportWrittenMessage } from './reportBuild.js';

const category = localize2('saengine.category', "SAEngine");

/** Set by the SAEngine model contribution while a project is open. */
const projectOpen = ContextKeyExpr.has('saengineProjectOpen');

/** The view the Model Explorer contributes; the command sits in its title bar overflow. */
const MODEL_EXPLORER_VIEW_ID = 'saengine.modelExplorer';

/** Command id of the file explorer's "Reveal in File Explorer" (desktop only). */
const REVEAL_IN_OS_COMMAND_ID = 'revealFileInOS';

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.report.print',
			title: localize2('saengine.printReport', "Print Design Report"),
			category,
			icon: Codicon.filePdf,
			f1: true,
			precondition: projectOpen,
			menu: [
				{ id: MenuId.MenubarFileMenu, group: '4_save_print', order: 1, when: projectOpen },
				{ id: MenuId.ViewTitle, group: '9_report', order: 1, when: ContextKeyExpr.and(projectOpen, ContextKeyExpr.equals('view', MODEL_EXPLORER_VIEW_ID)) },
			],
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		const projectService = accessor.get(ISaengineProjectService);
		const commandService = accessor.get(ICommandService);
		const progressService = accessor.get(IProgressService);
		const notificationService = accessor.get(INotificationService);
		const openerService = accessor.get(IOpenerService);

		const project = projectService.project;
		if (!project) {
			notificationService.info(localize('report.noProject', "Open a SAEngine project to print its design report."));
			return;
		}

		const request: IReportBuildRequest = { projectRoot: project.root.fsPath };
		let result: IReportBuildResult | undefined;
		try {
			result = await progressService.withProgress({
				location: ProgressLocation.Notification,
				title: localize('report.progress', "Printing the design report of {0}", project.name),
			}, () => commandService.executeCommand<IReportBuildResult>(BUILD_REPORT_COMMAND_ID, request));
		} catch (error) {
			notificationService.error(localize('report.failed', "The design report could not be printed: {0}", toErrorMessage(error)));
			return;
		}

		const problems = reportProblems(result);
		if (problems.length || !result?.path) {
			notificationService.notify({
				severity: Severity.Error,
				message: problems.length === 1
					? localize('report.problem', "The design report was not printed: {0}", problems[0])
					: localize('report.problems', "The design report was not printed: {0}", problems.join(' ')),
			});
			return;
		}

		const pdf = URI.file(result.path);
		// Open in the operating system's PDF viewer.
		await openerService.open(pdf, { openExternal: true });
		notificationService.prompt(
			result.warnings?.length ? Severity.Warning : Severity.Info,
			reportWrittenMessage(result),
			[
				{
					label: localize('report.open', "Open Report"),
					run: () => openerService.open(pdf, { openExternal: true }),
				},
				{
					label: localize('report.reveal', "Reveal in File Explorer"),
					run: () => commandService.executeCommand(REVEAL_IN_OS_COMMAND_ID, pdf),
				},
			],
		);
	}
});
