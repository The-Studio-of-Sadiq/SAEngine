/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/saengineTokens.css';
import './media/placeholderEditor.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType } from '../../../../base/browser/dom.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { isEqual, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { DEFAULT_EDITOR_ASSOCIATION, IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { DEVELOPER_MODE_SETTING } from '../../../services/saengineProject/common/developerMode.js';
import { isPlaceholder } from '../../../services/saengineProject/common/partStatus.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { partName } from './projectParts.js';
import { PlaceholderEditorInput } from './placeholderEditorInput.js';

/**
 * The parts whose editors are not built yet, with the one sentence their page says. A part
 * leaves this list when its editor arrives (that editor registers for the part's main file).
 */
export const PLACEHOLDER_PARTS: readonly { readonly part: string; readonly description: () => string }[] = [
	{ part: 'soil', description: () => localize('placeholder.soil', "Boreholes with SPT, lab data, bearing capacity and settlement, and liquefaction. Coming in the next phase.") },
	{ part: 'mep', description: () => localize('placeholder.mep', "Mechanical, electrical and plumbing services and their loads on the structure. Planned for later.") },
	{ part: 'substructure', description: () => localize('placeholder.substructure', "Footings, piles and pile caps, and rafts, designed from the analysis reactions. Coming in the next phase.") },
];

/** What a part's main file holds, for the page. */
function fileState(text: string | undefined, part: string): 'placeholder' | 'data' {
	if (text === undefined || !text.trim()) {
		return 'placeholder';
	}
	try {
		const value = JSON.parse(text);
		return typeof value === 'object' && value !== null && !Array.isArray(value) && isPlaceholder(value, part) ? 'placeholder' : 'data';
	} catch {
		return 'data';
	}
}

/**
 * The calm page of a part that is not built yet: its number and name and one sentence of what
 * it will hold. Developer mode adds "Open as JSON"; a file that already holds data (written by
 * hand or a later version) says so and always offers it, so nothing in it is out of reach.
 */
export class PlaceholderEditor extends EditorPane {

	static readonly ID = PlaceholderEditorInput.EDITOR_ID;

	private container!: HTMLElement;
	private model: ITextModel | undefined;
	private link: HTMLElement | undefined;
	private readonly inputDisposables = this._register(new DisposableStore());
	private readonly renderDisposables = this._register(new DisposableStore());

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@IEditorService private readonly editorService: IEditorService,
	) {
		super(PlaceholderEditor.ID, group, telemetryService, themeService, storageService);
		this._register(this.configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration(DEVELOPER_MODE_SETTING)) {
				this.render();
			}
		}));
		this._register(this.projectService.onDidChangeProject(() => this.render()));
	}

	protected createEditor(parent: HTMLElement): void {
		this.container = append(parent, $('.saengine-placeholder', { tabIndex: -1 }));
	}

	override async setInput(input: PlaceholderEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.inputDisposables.clear();
		this.model = undefined;
		this.render();
		try {
			const reference = await this.textModelService.createModelReference(input.resource);
			if (token.isCancellationRequested || this.input !== input) {
				reference.dispose();
				return;
			}
			this.inputDisposables.add(reference);
			this.model = reference.object.textEditorModel;
			this.inputDisposables.add(this.model.onDidChangeContent(() => this.render()));
		} catch {
			// A missing file is the same as the placeholder: the project service recreates it.
		}
		this.render();
	}

	override clearInput(): void {
		this.inputDisposables.clear();
		this.renderDisposables.clear();
		this.model = undefined;
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.container.style.width = `${dimension.width}px`;
		this.container.style.height = `${dimension.height}px`;
	}

	override focus(): void {
		super.focus();
		(this.link ?? this.container).focus();
	}

	private render(): void {
		const input = this.input as PlaceholderEditorInput | undefined;
		if (!input || !this.container) {
			return;
		}
		this.renderDisposables.clear();
		this.link = undefined;
		clearNode(this.container);
		const part = partById(input.part);
		const index = this.projectService.parts.findIndex(p => p.id === input.part);
		const page = append(this.container, $('.page'));
		const heading = append(page, $('h1'));
		if (index >= 0) {
			append(heading, $('span.number', undefined, String(index + 1)));
		}
		append(heading, $('span.name', undefined, part ? partName(part) : input.part));
		const description = PLACEHOLDER_PARTS.find(p => p.part === input.part)?.description();
		if (description) {
			append(page, $('p.description', undefined, description));
		}

		const hasData = fileState(this.model && !this.model.isDisposed() ? this.model.getValue() : undefined, input.part) === 'data';
		if (hasData) {
			append(page, $('p.note', undefined, localize('placeholder.hasData', "This file already holds data that this version cannot show yet.")));
		}
		if (hasData || this.configurationService.getValue<boolean>(DEVELOPER_MODE_SETTING) === true) {
			const link = this.link = append(page, $<HTMLAnchorElement>('a.open-json', { role: 'button', tabIndex: 0 }, localize('placeholder.openJson', "Open as JSON")));
			const open = () => void this.openAsJson(input);
			this.renderDisposables.add(addDisposableListener(link, EventType.CLICK, open));
			this.renderDisposables.add(addDisposableListener(link, EventType.KEY_DOWN, e => {
				if (e.key === 'Enter' || e.key === ' ') {
					e.preventDefault();
					open();
				}
			}));
		}
	}

	/** Shows the file in the text editor, in place of this page. */
	private async openAsJson(input: PlaceholderEditorInput): Promise<void> {
		await this.editorService.replaceEditors([{
			editor: input,
			replacement: { resource: input.resource, options: { override: DEFAULT_EDITOR_ASSOCIATION.id, pinned: true } },
		}], this.group);
	}
}

/** The id of the part whose main file `resource` is, among the parts this page stands in for. */
export function placeholderPartOf(resource: URI | undefined, root: URI | undefined): string | undefined {
	if (!resource || !root) {
		return undefined;
	}
	for (const { part } of PLACEHOLDER_PARTS) {
		const definition = partById(part);
		if (definition?.mainFile && isEqual(resource, joinPath(root, definition.folder, definition.mainFile))) {
			return part;
		}
	}
	return undefined;
}
