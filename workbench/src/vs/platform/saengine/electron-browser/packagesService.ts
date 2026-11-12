/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { registerMainProcessRemoteService } from '../../ipc/electron-browser/services.js';
import { ISaenginePackagesService, PACKAGES_CHANNEL } from '../common/packages.js';

registerMainProcessRemoteService(ISaenginePackagesService, PACKAGES_CHANNEL);
