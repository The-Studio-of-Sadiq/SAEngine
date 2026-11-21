/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineActionsService } from '../../../services/saengineProject/common/saengineActions.js';
import { ISaengineProject } from '../../../services/saengineProject/common/saengineProject.js';

export type DataPanelScalar = string | number | boolean | null | undefined;
export type DataPanelValues = { [key: string]: string | number | boolean };
export type DataPanelTone = 'neutral' | 'ok' | 'warn' | 'fail';

export interface IDataPanelFieldOption {
	readonly value: string;
	readonly label: string;
}

export interface IDataPanelField {
	readonly key: string;
	readonly label: string;
	readonly type: 'text' | 'number' | 'select' | 'checkbox' | 'file' | 'folder';
	readonly defaultValue: string | number | boolean;
	readonly options?: readonly IDataPanelFieldOption[];
	readonly step?: string;
	readonly min?: number;
	readonly max?: number;
	readonly placeholder?: string;
	readonly help?: string;
	readonly filters?: readonly { readonly name: string; readonly extensions: readonly string[] }[];
	readonly saveMode?: boolean;
	readonly visibleWhen?: (values: DataPanelValues) => boolean;
}

export interface IDataPanelColumn {
	readonly key: string;
	readonly title: string;
	readonly type?: 'string' | 'number' | 'status';
	readonly align?: 'left' | 'right';
}

export type DataPanelRow = { readonly [key: string]: DataPanelScalar };

export interface IDataPanelTable {
	readonly id: string;
	readonly title: string;
	readonly columns: readonly IDataPanelColumn[];
	readonly rows: readonly DataPanelRow[];
	readonly emptyMessage?: string;
}

export interface IDataPanelMetric {
	readonly label: string;
	readonly value: string;
	readonly tone?: DataPanelTone;
}

export interface IDataPanelAction {
	readonly id: string;
	readonly label: string;
	readonly icon?: ThemeIcon;
	readonly run: (context: IDataPanelContext, values: DataPanelValues, result: IDataPanelResult | undefined) => Promise<void> | void;
}

export interface IDataPanelOutputFile {
	readonly label: string;
	readonly path: string;
}

export interface IDataPanelEmptyState {
	readonly icon?: ThemeIcon;
	readonly title: string;
	readonly text: string;
	readonly action?: IDataPanelAction;
}

export interface IDataPanelResult {
	readonly metrics?: readonly IDataPanelMetric[];
	readonly tables: readonly IDataPanelTable[];
	readonly notes?: readonly string[];
	readonly problems?: readonly string[];
	readonly outputFiles?: readonly IDataPanelOutputFile[];
	readonly emptyState?: IDataPanelEmptyState;
	readonly primaryAction?: IDataPanelAction;
	readonly statusText?: string;
	readonly statusSeverity?: 'info' | 'warning' | 'error';
	readonly updatedOptions?: { readonly [fieldKey: string]: readonly IDataPanelFieldOption[] };
	readonly updatedValues?: Partial<DataPanelValues>;
}

export interface IDataPanelContext {
	readonly project: ISaengineProject | undefined;
	readonly commandService: ICommandService;
	readonly actionsService: ISaengineActionsService;
	readonly editorService: IEditorService;
	readonly fileService: IFileService;
	readonly openerService: IOpenerService;
	readonly notificationService: INotificationService;
	readonly fileDialogService: IFileDialogService;
	readonly refresh: () => Promise<void>;
	engineRequest<T = unknown>(method: string, params?: object): Promise<T>;
}

export interface IEngineDataPanelDescriptor {
	readonly id: string;
	readonly title: string;
	readonly part?: string;
	readonly help: string;
	readonly icon?: ThemeIcon;
	readonly requiresProject?: boolean;
	readonly autoRun?: boolean;
	readonly runLabel?: string;
	readonly fields?: readonly IDataPanelField[];
	readonly secondaryActions?: readonly IDataPanelAction[];
	readonly loadInitial?: (context: IDataPanelContext, values: DataPanelValues) => Promise<{
		readonly values?: Partial<DataPanelValues>;
		readonly options?: { readonly [fieldKey: string]: readonly IDataPanelFieldOption[] };
		readonly note?: string;
	} | undefined>;
	readonly run: (context: IDataPanelContext, values: DataPanelValues) => Promise<IDataPanelResult>;
}

const REGISTRY = new Map<string, IEngineDataPanelDescriptor>();

export function registerEngineDataPanel(descriptor: IEngineDataPanelDescriptor): void {
	REGISTRY.set(descriptor.id, descriptor);
}

export function getEngineDataPanel(id: string): IEngineDataPanelDescriptor | undefined {
	return REGISTRY.get(id);
}

export function listEngineDataPanels(): readonly IEngineDataPanelDescriptor[] {
	return Array.from(REGISTRY.values());
}

export const OPEN_DATA_PANEL_COMMAND = 'saengine.dataPanel.open';

export function panelDescriptorOrFallback(id: string): IEngineDataPanelDescriptor | undefined {
	return REGISTRY.get(id);
}

export function defaultPanelIcon(descriptor: IEngineDataPanelDescriptor | undefined): ThemeIcon {
	return descriptor?.icon ?? Codicon.table;
}

export function formatCell(value: DataPanelScalar): string {
	if (value === null || value === undefined || value === '') {
		return '–';
	}
	if (typeof value === 'boolean') {
		return value ? 'Yes' : 'No';
	}
	if (typeof value === 'number') {
		if (!Number.isFinite(value)) {
			return '–';
		}
		if (Number.isInteger(value)) {
			return String(value);
		}
		return String(Number(value.toFixed(3)));
	}
	return String(value);
}

export function toCsvRows(table: IDataPanelTable): (string | number | undefined)[][] {
	const header = table.columns.map(c => c.title);
	const body = table.rows.map(row =>
		table.columns.map(col => {
			const v = row[col.key];
			if (typeof v === 'number' || typeof v === 'string') {
				return v;
			}
			if (typeof v === 'boolean') {
				return v ? 'Yes' : 'No';
			}
			return undefined;
		})
	);
	return [header, ...body];
}

export function statusTone(value: DataPanelScalar): DataPanelTone {
	if (value === true) {
		return 'ok';
	}
	if (value === false) {
		return 'fail';
	}
	const s = String(value ?? '').trim().toLowerCase();
	if (s === 'pass' || s === 'ok' || s === 'passed' || s === 'yes' || s === 'added' || s === 'valid') {
		return 'ok';
	}
	if (s === 'warn' || s === 'warning' || s === 'warnings' || s === 'changed' || s === 'placeholder' || s === 'modified') {
		return 'warn';
	}
	if (s === 'fail' || s === 'failed' || s === 'error' || s === 'errors' || s === 'removed' || s === 'deleted' || s === 'problems' || s === 'missing') {
		return 'fail';
	}
	return 'neutral';
}

export type OpenPanelRunner = (accessor: ServicesAccessor) => Promise<unknown>;
