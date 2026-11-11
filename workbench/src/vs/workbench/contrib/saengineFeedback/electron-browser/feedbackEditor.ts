/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/feedback.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { DomScrollableElement } from '../../../../base/browser/ui/scrollbar/scrollableElement.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { basename } from '../../../../base/common/resources.js';
import { ScrollbarVisibility } from '../../../../base/common/scrollable.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { IClipboardService } from '../../../../platform/clipboard/common/clipboardService.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INativeHostService } from '../../../../platform/native/common/native.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IProductService } from '../../../../platform/product/common/productService.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { EditorInputCapabilities, IEditorOpenContext, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { buildReport, DIAGNOSTICS_SETTING, FEEDBACK_DESTINATION, FeedbackKind, formProblem, IFeedbackForm, issueRequest, kindLabel } from '../common/feedback.js';
import { ISaengineDiagnosticsService } from './diagnosticsService.js';

const feedbackIcon = registerIcon('saengine-feedback-editor-icon', Codicon.feedback, localize('saengineFeedbackIcon', "Icon of the SAEngine bug report and feedback form."));

/** The export of the project as a .civil archive (asks where), for a report that needs the files. */
const EXPORT_ARCHIVE_COMMAND = 'saengine.project.exportArchive';

/** Help > Report a Bug / Send Feedback: one form, opened with the kind preset. */
export class FeedbackEditorInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.feedback';
	static readonly EDITOR_ID = 'workbench.editor.saengine.feedback';

	private static _instance: FeedbackEditorInput | undefined;
	static instance(kind: FeedbackKind): FeedbackEditorInput {
		if (!FeedbackEditorInput._instance || FeedbackEditorInput._instance.isDisposed()) {
			FeedbackEditorInput._instance = new FeedbackEditorInput();
		}
		FeedbackEditorInput._instance.kind = kind;
		return FeedbackEditorInput._instance;
	}

	kind: FeedbackKind = 'bug';
	/** A screenshot taken when the form was opened (the window as the engineer saw it). */
	screenshot: URI | undefined;

	readonly resource = URI.from({ scheme: 'saengine-feedback', path: '/form' });

	override get typeId(): string { return FeedbackEditorInput.ID; }
	override get editorId(): string { return FeedbackEditorInput.EDITOR_ID; }
	override get capabilities(): EditorInputCapabilities { return EditorInputCapabilities.Readonly | EditorInputCapabilities.Singleton; }
	override getName(): string { return localize('feedback.name', "Report a Bug / Send Feedback"); }
	override getIcon(): ThemeIcon { return feedbackIcon; }
	override matches(other: EditorInput | IUntypedEditorInput): boolean { return super.matches(other) || other instanceof FeedbackEditorInput; }
}

interface IFormControls {
	readonly kind: HTMLSelectElement;
	readonly title: HTMLInputElement;
	readonly description: HTMLTextAreaElement;
	readonly steps: HTMLTextAreaElement;
	readonly stepsField: HTMLElement;
	readonly email: HTMLInputElement;
	readonly diagnostics: HTMLInputElement;
	readonly screenshot: HTMLInputElement;
	readonly status: HTMLInputElement;
	readonly files: HTMLInputElement;
}

/**
 * The bug report and feedback form (U2). It shows the whole report before anything is sent and
 * then opens the destination ({@link FEEDBACK_DESTINATION}: a pre-filled GitHub issue, public) in
 * the browser; the engineer submits it there. Attachments go only when ticked; project files
 * never, unless the engineer ticks them, and then as an archive they attach themselves.
 */
export class FeedbackEditor extends EditorPane {

	static readonly ID = FeedbackEditorInput.EDITOR_ID;

	private frame!: EditorFrame;
	private body!: HTMLElement;
	private scrollable!: DomScrollableElement;
	private controls: IFormControls | undefined;
	private previewBox!: HTMLElement;
	private readonly formDisposables = this._register(new DisposableStore());
	private readonly previewDisposables = this._register(new DisposableStore());

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@ISaengineDiagnosticsService private readonly diagnostics: ISaengineDiagnosticsService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@IOpenerService private readonly openerService: IOpenerService,
		@IClipboardService private readonly clipboardService: IClipboardService,
		@INativeHostService private readonly nativeHostService: INativeHostService,
		@INotificationService private readonly notificationService: INotificationService,
		@ICommandService private readonly commandService: ICommandService,
		@IProductService private readonly productService: IProductService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
	) {
		super(FeedbackEditor.ID, group, telemetryService, themeService, storageService);
	}

	protected createEditor(parent: HTMLElement): void {
		this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, { id: FeedbackEditor.ID, ariaLabel: localize('feedback.toolbar', "Report a Bug / Send Feedback") }));
		this.frame.element.classList.add('saengine-feedback-editor');
		this.frame.setTitle(localize('feedback.title', "Report a Bug / Send Feedback"));
		this.frame.setHelp(localize('feedback.help', "Tell the SAEngine developers about a problem or an idea. You see the whole report before anything is sent; it is then opened as a new GitHub issue in your browser, where you submit it. GitHub issues are public."));
		this.body = $('.feedback-body');
		this.scrollable = this._register(new DomScrollableElement(this.body, { horizontal: ScrollbarVisibility.Hidden, vertical: ScrollbarVisibility.Auto }));
		append(this.frame.main, this.scrollable.getDomNode()).classList.add('feedback-scroll');
		this._register(this.frame.onDidLayoutMain(() => this.scrollable.scanDomNode()));
	}

	override async setInput(input: FeedbackEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.render(input);
	}

	private render(input: FeedbackEditorInput): void {
		this.formDisposables.clear();
		this.previewDisposables.clear();
		clearNode(this.body);

		const notice = append(this.body, $('.feedback-public', { role: 'note' }));
		append(notice, $(ThemeIcon.asCSSSelector(Codicon.globe)));
		append(notice, $('span', undefined, localize('feedback.publicNotice', "GitHub issues are public: anyone can read what you send. Leave out client names, addresses and anything confidential about the project.")));

		const field = (label: string, control: HTMLElement, note?: string) => {
			const row = append(this.body, $('.feedback-field'));
			const id = `saengine-feedback-${label.replace(/\W+/g, '-').toLowerCase()}`;
			control.id = id;
			append(row, $('label', { for: id }, label));
			append(row, control);
			if (note) {
				append(row, $('.feedback-note', undefined, note));
			}
			return row;
		};
		const kind = $<HTMLSelectElement>('select.feedback-input');
		for (const k of ['bug', 'feedback', 'feature'] as const) {
			const option = append(kind, $<HTMLOptionElement>('option', { value: k }, kindLabel(k)));
			option.selected = k === input.kind;
		}
		field(localize('feedback.kind', "Kind"), kind);
		const title = $<HTMLInputElement>('input.feedback-input', { type: 'text', maxlength: '120', placeholder: localize('feedback.titlePlaceholder', "e.g. Column design stops at storey 7") });
		field(localize('feedback.titleLabel', "Title"), title);
		const description = $<HTMLTextAreaElement>('textarea.feedback-input', { rows: '6', placeholder: localize('feedback.descriptionPlaceholder', "What happened, and what you expected (or what you would like SAEngine to do).") });
		field(localize('feedback.description', "Description"), description);
		const steps = $<HTMLTextAreaElement>('textarea.feedback-input', { rows: '4', placeholder: localize('feedback.stepsPlaceholder', "1. Open the floor plan\n2. ...") });
		const stepsField = field(localize('feedback.steps', "Steps to reproduce"), steps);
		const email = $<HTMLInputElement>('input.feedback-input', { type: 'email', placeholder: localize('feedback.emailPlaceholder', "Optional") });
		field(localize('feedback.email', "E-mail"), email, localize('feedback.emailNote', "Only if you want an answer by e-mail: it is shown in the public issue."));

		append(this.body, $('h3.feedback-heading', undefined, localize('feedback.attach', "Attach (only what you tick)")));
		const check = (label: string, checked: boolean, note: string) => {
			const row = append(this.body, $('.feedback-check'));
			const box = append(row, $<HTMLInputElement>('input', { type: 'checkbox' }));
			box.checked = checked;
			const text = append(row, $('label'));
			append(text, $('span', undefined, label));
			append(text, $('.feedback-note', undefined, note));
			this.formDisposables.add(addDisposableListener(text, EventType.CLICK, () => { box.checked = !box.checked; }));
			return box;
		};
		const diagnostics = check(localize('feedback.attachDiagnostics', "Diagnostics bundle"), this.configurationService.getValue<boolean>(DIAGNOSTICS_SETTING) === true,
			localize('feedback.attachDiagnosticsNote', "SAEngine's version, your operating system, the code pack in use and recent error messages, with names, folders and e-mail addresses removed. Shown in full below before sending."));
		const screenshot = check(localize('feedback.attachScreenshot', "Screenshot of the window"), false,
			input.screenshot
				? localize('feedback.attachScreenshotNote', "Taken when you opened this form ({0}). You attach it yourself: SAEngine shows the file when the issue page opens.", basename(input.screenshot))
				: localize('feedback.attachScreenshotNone', "Not available: the window could not be captured."));
		screenshot.disabled = !input.screenshot;
		const status = check(localize('feedback.attachStatus', "Project status summary"), false,
			this.projectService.project
				? localize('feedback.attachStatusNote', "Each part's state (done, out of date, failing), without names, values or files.")
				: localize('feedback.attachStatusNone', "No project is open."));
		status.disabled = !this.projectService.project;
		const files = check(localize('feedback.attachFiles', "Project files"), false,
			localize('feedback.attachFilesNote', "Never sent unless you tick this: SAEngine exports the project as a .civil archive and you attach it to the issue yourself. Everyone can download it there."));
		files.disabled = !this.projectService.project;
		this.controls = { kind, title, description, steps, stepsField, email, diagnostics, screenshot, status, files };

		const showSteps = () => stepsField.classList.toggle('hidden', kind.value !== 'bug');
		showSteps();
		this.formDisposables.add(addDisposableListener(kind, EventType.CHANGE, showSteps));

		const actions = append(this.body, $('.feedback-actions'));
		const preview = this.formDisposables.add(new Button(actions, { ...defaultButtonStyles }));
		preview.label = localize('feedback.preview', "Preview Report");
		this.formDisposables.add(preview.onDidClick(() => this.preview()));
		this.previewBox = append(this.body, $('.feedback-preview'));
		this.scrollable.scanDomNode();
		title.focus();
	}

	private form(): IFeedbackForm | undefined {
		const c = this.controls;
		return c && { kind: c.kind.value as FeedbackKind, title: c.title.value, description: c.description.value, steps: c.steps.value, email: c.email.value };
	}

	private async preview(): Promise<void> {
		const c = this.controls;
		const form = this.form();
		const input = this.input instanceof FeedbackEditorInput ? this.input : undefined;
		if (!c || !form || !input) {
			return;
		}
		this.previewDisposables.clear();
		clearNode(this.previewBox);
		const problem = formProblem(form);
		if (problem) {
			append(this.previewBox, $('.feedback-problem', { role: 'alert' }, problem));
			this.scrollable.scanDomNode();
			return;
		}
		const attachedFiles: string[] = [];
		if (c.screenshot.checked && input.screenshot) {
			attachedFiles.push(localize('feedback.fileScreenshot', "a screenshot of the window ({0})", basename(input.screenshot)));
		}
		if (c.files.checked) {
			attachedFiles.push(localize('feedback.fileProject', "the project as a .civil archive"));
		}
		const os = await this.nativeHostService.getOSProperties();
		const report = buildReport(form, {
			diagnostics: c.diagnostics.checked ? await this.diagnostics.bundle() : undefined,
			projectStatus: c.status.checked ? this.diagnostics.projectStatus() : undefined,
			files: attachedFiles,
		}, { version: this.productService.version, os: `${os.platform} ${os.release} ${os.arch}` });

		append(this.previewBox, $('h3.feedback-heading', undefined, localize('feedback.previewHeading', "This is exactly what will be sent")));
		append(this.previewBox, $('.feedback-note', undefined, localize('feedback.previewNote', "It opens as a new issue at {0} in your browser; nothing is sent until you submit it there. The issue is public.", FEEDBACK_DESTINATION.url)));
		append(this.previewBox, $('pre.feedback-report', { tabIndex: 0, 'aria-label': localize('feedback.reportLabel', "The report") }, `${report.title}\n\n${report.body}`));
		const actions = append(this.previewBox, $('.feedback-actions'));
		const open = this.previewDisposables.add(new Button(actions, { ...defaultButtonStyles }));
		open.label = localize('feedback.openIssue', "Open GitHub Issue");
		this.previewDisposables.add(open.onDidClick(() => this.send(report, c, input)));
		const copy = this.previewDisposables.add(new Button(actions, { ...defaultButtonStyles, secondary: true }));
		copy.label = localize('feedback.copy', "Copy Report");
		this.previewDisposables.add(copy.onDidClick(() => this.clipboardService.writeText(`${report.title}\n\n${report.body}`)));
		this.scrollable.scanDomNode();
	}

	private async send(report: { readonly title: string; readonly body: string }, c: IFormControls, input: FeedbackEditorInput): Promise<void> {
		const request = issueRequest(report);
		if (request.clipboard) {
			await this.clipboardService.writeText(request.clipboard);
			this.notificationService.info(localize('feedback.inClipboard', "The report is long, so it is in the clipboard: paste it into the issue page (Ctrl+V)."));
		}
		if (c.files.checked) {
			await this.commandService.executeCommand(EXPORT_ARCHIVE_COMMAND).catch(error => this.notificationService.warn(localize('feedback.exportFailed', "The project could not be exported: {0}", String(error))));
		}
		await this.openerService.open(request.url, { openExternal: true });
		if (c.screenshot.checked && input.screenshot) {
			await this.nativeHostService.showItemInFolder(input.screenshot.fsPath);
		}
	}

	override layout(dimension: Dimension): void {
		this.frame.layout(dimension.width, dimension.height);
	}

	override focus(): void {
		super.focus();
		this.controls?.title.focus();
	}
}
