/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/saengineTokens.css';
import './media/importReport.css';
import { $, append, clearNode, Dimension } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { DomScrollableElement } from '../../../../base/browser/ui/scrollbar/scrollableElement.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { ScrollbarVisibility } from '../../../../base/common/scrollable.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { ImportReportInput } from './importReportInput.js';
import { ProjectOpener } from './projectOpener.js';
import { countRows, describeCarried, describeImportSummary, describeItem, describeNotCarried, formatLabel, IImportReportItem, needsReview, notCarriedTotal, sameFolder } from './structuralImportModel.js';

/**
 * The report of an import from ETABS, STAAD.Pro or SAP2000: the counts by kind, then what was
 * approximated, skipped and warned about, each with how many and a few examples. Shown before
 * the new project opens, and once more in the project's window.
 */
export class ImportReportEditor extends EditorPane {

	private container!: HTMLElement;
	private scrollable!: DomScrollableElement;
	private readonly opener: ProjectOpener;
	private readonly renderDisposables = this._register(new DisposableStore());

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService instantiationService: IInstantiationService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@INotificationService private readonly notificationService: INotificationService,
	) {
		super(ImportReportInput.EDITOR_ID, group, telemetryService, themeService, storageService);
		this.opener = instantiationService.createInstance(ProjectOpener);
		this._register(this.projectService.onDidChangeProject(() => this.render()));
	}

	protected createEditor(parent: HTMLElement): void {
		this.container = $('.saengine-import-report', { tabIndex: -1 });
		this.scrollable = this._register(new DomScrollableElement(this.container, { horizontal: ScrollbarVisibility.Hidden, vertical: ScrollbarVisibility.Auto }));
		append(parent, this.scrollable.getDomNode());
	}

	override async setInput(input: ImportReportInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.render();
	}

	override clearInput(): void {
		this.renderDisposables.clear();
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.container.style.width = `${dimension.width}px`;
		this.container.style.height = `${dimension.height}px`;
		this.scrollable.scanDomNode();
	}

	override focus(): void {
		super.focus();
		this.container.focus();
	}

	private render(): void {
		const input = this.input;
		if (!(input instanceof ImportReportInput)) {
			return;
		}
		this.renderDisposables.clear();
		clearNode(this.container);
		const { entry } = input;
		const report = entry.report;
		const page = append(this.container, $('.page'));

		const header = append(page, $('.header'));
		append(header, $('h1', undefined, localize('importReport.title', "Import Report")));
		const facts = [
			report.version ? localize('importReport.formatVersion', "{0} {1}", formatLabel(report.format), report.version) : formatLabel(report.format),
			...(entry.file || report.source ? [(entry.file ?? report.source)!.replace(/^.*[\\/]/, '')] : []),
			...(report.units ? [localize('importReport.units', "units {0}", report.units)] : []),
		];
		append(header, $('p.facts', undefined, facts.join(' · ')));
		append(header, $('p.path', { title: entry.root }, localize('importReport.into', "Project: {0}", entry.root)));

		const summary = append(page, $(`.summary${needsReview(report) ? '.review' : '.clean'}`));
		append(summary, $(`span.summary-icon${ThemeIcon.asCSSSelector(needsReview(report) ? Codicon.warning : Codicon.check)}`));
		append(summary, $('span.summary-text', undefined, describeImportSummary(report)));
		const isOpen = !!this.projectService.project && sameFolder(this.projectService.project.root.fsPath, entry.root);
		if (!isOpen) {
			const open = this.renderDisposables.add(new Button(summary, defaultButtonStyles));
			open.label = localize('importReport.open', "Open Project");
			this.renderDisposables.add(open.onDidClick(() => {
				this.opener.open(URI.file(entry.root)).catch(error => this.notificationService.error(error));
			}));
		}

		const counts = append(page, $('section.counts'));
		append(counts, $('h2', undefined, localize('importReport.imported', "Imported")));
		const grid = append(counts, $('.count-grid'));
		for (const row of countRows(report)) {
			const cell = append(grid, $(`.count${row.count ? '' : '.zero'}`));
			append(cell, $('span.count-value', undefined, row.count.toLocaleString()));
			append(cell, $('span.count-label', undefined, row.label));
		}

		const notCarried = describeNotCarried(report);
		const carried = describeCarried(report);
		if (notCarried || carried) {
			const loads = append(page, $(`section.loads${notCarried ? '.lost' : ''}`));
			append(loads, $('h2', undefined, localize('importReport.loads', "Loads")));
			if (notCarried) {
				append(loads, $('p.not-carried', undefined, localize('importReport.notCarried', "Not carried over: {0} (total {1} kN). Add these loads in SAEngine, or check that its own loads cover them.", notCarried, Math.round(notCarriedTotal(report) * 10) / 10)));
			}
			if (carried) {
				append(loads, $('p.hint', undefined, localize('importReport.carried', "Carried over: {0}.", carried)));
			}
		}

		if (report.unread) {
			append(page, $('p.unread', undefined, localize('importReport.unread', "{0} report lines could not be read by this version of SAEngine: see the import's own report file, or import again with an updated SAEngine.", report.unread)));
		}

		this.renderItems(page, 'approximated', localize('importReport.approximated', "Approximated"),
			localize('importReport.approximatedHint', "Imported, but not exactly as in the file: check these before relying on the results."), report.approximated);
		this.renderItems(page, 'skipped', localize('importReport.skipped', "Skipped"),
			localize('importReport.skippedHint', "Not imported: add them in SAEngine if the design needs them."), report.skipped);
		this.renderItems(page, 'warnings', localize('importReport.warnings', "Warnings"), undefined, report.warnings);
		if (!needsReview(report)) {
			append(page, $('p.muted', undefined, localize('importReport.nothingElse', "Everything in the file was imported as it is.")));
		}
		append(page, $('p.muted.next-steps', undefined, localize('importReport.nextSteps', "Next: review 03 Materials and 04 Objects, then Derive and Run All. The loads and combinations are in 06 BIM and 02 Project Settings.")));
		this.scrollable.scanDomNode();
	}

	private renderItems(page: HTMLElement, kind: string, title: string, hint: string | undefined, items: readonly IImportReportItem[]): void {
		if (!items.length) {
			return;
		}
		const section = append(page, $(`section.items.${kind}`));
		const total = items.reduce((sum, item) => sum + item.count, 0);
		append(section, $('h2', undefined, localize('importReport.sectionCount', "{0} ({1})", title, total)));
		if (hint) {
			append(section, $('p.hint', undefined, hint));
		}
		const list = append(section, $('ul'));
		for (const item of items) {
			const li = append(list, $('li'));
			if (item.kind) {
				append(li, $('span.kind', undefined, item.kind));
			}
			append(li, $('span.text', undefined, describeItem(item)));
		}
	}
}
