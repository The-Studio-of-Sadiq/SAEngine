/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Emitter } from '../../../../base/common/event.js';
import { Disposable, IDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import type { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import type { ISaengineProject } from '../../../services/saengineProject/common/saengineProject.js';

/*
 * The model layout's rules without the workbench: the model views, the frame the Properties
 * panel shows, the tables of the Tables panel (modelView.ts, propertiesDock.ts, tablesView.ts).
 */

// ───────────────────────────── model view ─────────────────────────────

export type ModelViewKind = 'plan' | '3d' | 'analysis';

/** The part each model view opens; a special structure's plan is its structural model. */
export function modelViewPart(kind: ModelViewKind, project: Pick<ISaengineProject, 'type'>): string {
	switch (kind) {
		case '3d': return 'bim';
		case 'analysis': return 'fem';
		default: return project.type === 'structure' ? 'structure' : 'floorPlan';
	}
}

/** Bumped when the layout a project opens on changes, so it is set up once more for everyone. */
export const MODEL_LAYOUT_VERSION = 1;

/** Whether the model layout (Properties on the right, Tables below) still has to be set up for a profile at `stored`. */
export function needsModelLayout(stored: number): boolean {
	return stored < MODEL_LAYOUT_VERSION;
}

// ───────────────────────────── Properties panel ─────────────────────────────

/**
 * The frame the Properties panel shows for an editor pane's container: the outermost frame
 * inside it (an editor embedding another's frame shows its own), or undefined.
 */
export function frameOfContainer<T extends { readonly element: HTMLElement }>(frames: readonly T[], container: HTMLElement | undefined): T | undefined {
	if (!container) {
		return undefined;
	}
	const inside = frames.filter(frame => container.contains(frame.element));
	return inside.find(frame => !inside.some(other => other !== frame && other.element.contains(frame.element)));
}

// ───────────────────────────── Tables panel ─────────────────────────────

/** A table shown in a tab of the Tables panel. */
export interface ISaengineTable extends IDisposable {
	layout(width: number, height: number): void;
	/** The tab was shown (true) or another one was (false). */
	setVisible?(visible: boolean): void;
	focus?(): void;
}

export interface ISaengineTableDescriptor {
	/** Stable id: the panel remembers the tab shown by it. */
	readonly id: string;
	readonly label: () => string;
	/** Tabs are ordered by it, lowest first. */
	readonly order: number;
	/** Whether the open project has this table (a special structure has no floor plan); default: yes. */
	readonly when?: (project: ISaengineProject) => boolean;
	/** Creates the table into `container` (shown in the tab, filling it). */
	create(container: HTMLElement, instantiationService: IInstantiationService): ISaengineTable;
}

/** The tables the parts register, in order. */
export class SaengineTableRegistry extends Disposable {

	private readonly descriptors: ISaengineTableDescriptor[] = [];

	private readonly _onDidChange = this._register(new Emitter<void>());
	readonly onDidChange = this._onDidChange.event;

	register(descriptor: ISaengineTableDescriptor): IDisposable {
		this.descriptors.push(descriptor);
		this.descriptors.sort((a, b) => a.order - b.order);
		this._onDidChange.fire();
		return toDisposable(() => {
			const index = this.descriptors.indexOf(descriptor);
			if (index >= 0) {
				this.descriptors.splice(index, 1);
				this._onDidChange.fire();
			}
		});
	}

	/** The tables of `project`, in order (none without a project). */
	tablesOf(project: ISaengineProject | undefined): readonly ISaengineTableDescriptor[] {
		return project ? this.descriptors.filter(d => !d.when || d.when(project)) : [];
	}
}

/** The tab to show among `ids`: the remembered one while it is there, else the first. */
export function activeTableId(ids: readonly string[], remembered: string | undefined): string | undefined {
	return remembered && ids.includes(remembered) ? remembered : ids[0];
}
