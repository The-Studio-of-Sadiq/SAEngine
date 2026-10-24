/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { EditorInputCapabilities, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { ILastImport } from './structuralImportModel.js';

const importReportIcon = registerIcon('saengine-import-report-label-icon', Codicon.checklist, localize('saengineImportReportIcon', "Icon of the SAEngine import report."));

/** The report of an import from ETABS, STAAD.Pro or SAP2000: what was imported, approximated and skipped. */
export class ImportReportInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.importReport';
	static readonly EDITOR_ID = 'workbench.editor.saengine.importReport';

	readonly resource: URI;

	constructor(readonly entry: ILastImport) {
		super();
		this.resource = URI.from({ scheme: 'saengine-import-report', path: `/${entry.time}` });
	}

	override get typeId(): string {
		return ImportReportInput.ID;
	}

	override get editorId(): string {
		return ImportReportInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Readonly;
	}

	override getName(): string {
		return localize('saengineImportReport', "Import Report");
	}

	override getIcon(): ThemeIcon {
		return importReportIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		// One tab per import: a later import's report replaces nothing of an earlier one's.
		return super.matches(other) || (other instanceof ImportReportInput && other.entry.time === this.entry.time && other.entry.root === this.entry.root);
	}
}
