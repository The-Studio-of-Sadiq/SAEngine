/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../../base/common/event.js';
import { URI } from '../../../../base/common/uri.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';

/** A colleague in the same part during live co-editing, and what they have selected there. */
export interface ICoEditingColleague {
	readonly name: string;
	/** Their colour (`#rrggbb`), the same in every window. */
	readonly color?: string;
	/** The ids of the objects they have selected (members, storeys). */
	readonly selection: readonly string[];
}

export const ISaengineCoEditingPresenceService = createDecorator<ISaengineCoEditingPresenceService>('saengineCoEditingPresenceService');

/**
 * Who else is in a part file during live co-editing, so a part editor can show their selection
 * without knowing the co-editing engine: the desktop app's live co-editing feeds it, the editors
 * read it. Empty without live co-editing.
 */
export interface ISaengineCoEditingPresenceService {
	readonly _serviceBrand: undefined;

	/** Fires with the part file whose colleagues changed. */
	readonly onDidChange: Event<URI>;

	/** The colleagues in the part file `resource` (not this window). */
	colleagues(resource: URI): readonly ICoEditingColleague[];

	/** Sets the colleagues in `resource`; none forgets the part. */
	setColleagues(resource: URI, colleagues: readonly ICoEditingColleague[]): void;
}
