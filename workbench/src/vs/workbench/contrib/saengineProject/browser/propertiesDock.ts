/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Emitter, Event } from '../../../../base/common/event.js';
import { Disposable, IDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { Extensions as ConfigurationExtensions, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IViewsService } from '../../../services/views/common/viewsService.js';

/*
 * The Properties panel on the right of the window (the auxiliary bar) shows the properties panel
 * of the active SAEngine editor: the editor frame (editorFrame.ts) hands its panel's content to
 * the panel, which shows it in place of the editor's own column, so a member is seen and edited
 * where it always was (the same elements, listeners and edit paths), only in one place for every
 * editor. Without an editor that has one it shows the selection or the project summary
 * (saengineModel/browser/propertiesView.ts).
 */

/** The Properties panel's view (registered in saengineModel/browser/propertiesView.ts). */
export const PROPERTIES_VIEW_ID = 'saengine.properties';
export const PROPERTIES_VIEW_CONTAINER_ID = 'workbench.view.saengine.properties';

/** Where the SAEngine editors show their properties: the Properties panel, or each editor's own column. */
export const PROPERTIES_LOCATION_SETTING = 'saengine.properties.location';
export type PropertiesLocation = 'panel' | 'editor';

/** An editor frame whose properties panel can show in the Properties panel. */
export interface IPropertiesDockFrame {
	/** The frame's root element: the Properties panel shows the frame of the active editor. */
	readonly element: HTMLElement;
	/** Moves the panel's content into `host` (the Properties panel), or back into the frame. */
	dock(host: HTMLElement | undefined): void;
}

export const ISaenginePropertiesDockService = createDecorator<ISaenginePropertiesDockService>('saenginePropertiesDockService');

export interface ISaenginePropertiesDockService {
	readonly _serviceBrand: undefined;

	/** True when the editors' properties show in the Properties panel (the default). */
	readonly enabled: boolean;
	readonly onDidChangeEnabled: Event<void>;

	/** The frames with a properties panel, in the order they were created. */
	readonly frames: readonly IPropertiesDockFrame[];
	readonly onDidChangeFrames: Event<void>;
	register(frame: IPropertiesDockFrame): IDisposable;

	/** Opens the Properties panel (an editor's "Properties" button or menu entry). */
	reveal(): Promise<void>;
	/** Closes it (the editor's toggle when it shows). */
	hide(): void;
}

/**
 * The editor frame classes a docked panel's content keeps, so the editors' own styles for it
 * (`.saengine-floor-plan .sa-props-row.editable`) still apply: the `saengine-*` classes of the
 * frame and of its ancestors up to the editor pane.
 */
export function dockStyleClasses(element: HTMLElement): string[] {
	const classes = new Set<string>(['saengine-editor-frame']);
	for (let node: HTMLElement | null = element; node && !node.classList.contains('editor-instance') && !node.classList.contains('editor-group-container'); node = node.parentElement) {
		for (const name of Array.from(node.classList)) {
			if (name.startsWith('saengine-')) {
				classes.add(name);
			}
		}
	}
	return [...classes];
}

class SaenginePropertiesDockService extends Disposable implements ISaenginePropertiesDockService {

	declare readonly _serviceBrand: undefined;

	private readonly _frames: IPropertiesDockFrame[] = [];

	private readonly _onDidChangeFrames = this._register(new Emitter<void>());
	readonly onDidChangeFrames = this._onDidChangeFrames.event;

	private readonly _onDidChangeEnabled = this._register(new Emitter<void>());
	readonly onDidChangeEnabled = this._onDidChangeEnabled.event;

	constructor(
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@IViewsService private readonly viewsService: IViewsService,
	) {
		super();
		this._register(configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration(PROPERTIES_LOCATION_SETTING)) {
				this._onDidChangeEnabled.fire();
			}
		}));
	}

	get enabled(): boolean {
		return this.configurationService.getValue<PropertiesLocation>(PROPERTIES_LOCATION_SETTING) !== 'editor';
	}

	get frames(): readonly IPropertiesDockFrame[] {
		return this._frames;
	}

	register(frame: IPropertiesDockFrame): IDisposable {
		this._frames.push(frame);
		this._onDidChangeFrames.fire();
		return toDisposable(() => {
			const index = this._frames.indexOf(frame);
			if (index >= 0) {
				this._frames.splice(index, 1);
				this._onDidChangeFrames.fire();
			}
		});
	}

	async reveal(): Promise<void> {
		await this.viewsService.openView(PROPERTIES_VIEW_ID, false);
	}

	hide(): void {
		this.viewsService.closeView(PROPERTIES_VIEW_ID);
	}
}

registerSingleton(ISaenginePropertiesDockService, SaenginePropertiesDockService, InstantiationType.Delayed);

Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration).registerConfiguration({
	id: 'saengineLayout',
	title: localize('layout.settings', "SAEngine Layout"),
	type: 'object',
	properties: {
		[PROPERTIES_LOCATION_SETTING]: {
			type: 'string',
			enum: ['panel', 'editor'],
			enumDescriptions: [
				localize('properties.location.panel', "In the Properties panel on the right of the window, for whichever editor is active."),
				localize('properties.location.editor', "In a column on the right of each editor."),
			],
			default: 'panel',
			description: localize('properties.location', "Where the SAEngine editors show the properties of the selection."),
		},
	},
});
