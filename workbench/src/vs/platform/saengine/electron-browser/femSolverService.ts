/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { registerSharedProcessRemoteService } from '../../ipc/electron-browser/services.js';
import { FEM_SOLVER_CHANNEL, IFemSolverService } from '../common/femSolver.js';

registerSharedProcessRemoteService(IFemSolverService, FEM_SOLVER_CHANNEL);
