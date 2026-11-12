/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { registerMainProcessRemoteService } from '../../ipc/electron-browser/services.js';
import { CO_EDITING_CHANNEL, ISaengineCoEditingService } from '../common/coEditing.js';

registerMainProcessRemoteService(ISaengineCoEditingService, CO_EDITING_CHANNEL);
