/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { MenuId } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';

/** The ≡ menu in the header of the project sidebar. */
export const PROJECT_MENU = new MenuId('SaengineProjectMenu');

/** Whether a SAEngine project is open (set by the project service). */
export const ProjectOpenContext = ContextKeyExpr.has('saengineProjectOpen');
