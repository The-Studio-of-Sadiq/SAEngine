/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { joinPath } from '../../../../base/common/resources.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IFemSolverService, L12EngineMethod } from '../../../../platform/saengine/common/femSolver.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { ALL_PARTS, ISaengineProject } from '../../../services/saengineProject/common/saengineProject.js';
import { FemAnalysisRunner } from '../../saengineFem/electron-browser/femAnalysisRunner.js';

/** Calls an alpha 9 L12 backend method with the window's Python. */
export function callBackend(instantiationService: IInstantiationService, femSolverService: IFemSolverService, method: L12EngineMethod, params: object): Promise<unknown> {
	const python = instantiationService.createInstance(FemAnalysisRunner).resolvePython();
	return femSolverService.engine(python, method, params);
}

export function callBackendWith(accessor: ServicesAccessor, method: L12EngineMethod, params: object): Promise<unknown> {
	return callBackend(accessor.get(IInstantiationService), accessor.get(IFemSolverService), method, params);
}

/** Saves the project's edited part files: the backend reads them from disk. */
export async function saveProjectParts(textFileService: ITextFileService, project: ISaengineProject): Promise<void> {
	for (const part of ALL_PARTS) {
		const file = part.mainFile ? joinPath(project.root, part.folder, part.mainFile) : undefined;
		if (file && textFileService.isDirty(file)) {
			await textFileService.save(file);
		}
	}
}

export function bag(value: unknown): Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
