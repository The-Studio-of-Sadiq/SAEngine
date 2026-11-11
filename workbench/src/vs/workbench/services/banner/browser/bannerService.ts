/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { MarkdownString } from '../../../../base/common/htmlContent.js';
import { URI } from '../../../../base/common/uri.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { ILinkDescriptor } from '../../../../platform/opener/browser/link.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { IDisposable } from '../../../../base/common/lifecycle.js';

export interface IBannerItem {
	readonly id: string;
	readonly icon: ThemeIcon | URI | undefined;
	readonly message: string | MarkdownString;
	readonly actions?: ReadonlyArray<ILinkDescriptor>;
	readonly ariaLabel?: string;
	readonly onClose?: () => void;
	readonly closeLabel?: string;
	/** Higher-priority banners are shown first. Equal priorities use the most recently shown item. */
	readonly priority?: number;
	readonly neutral?: boolean;
}

export const IBannerService = createDecorator<IBannerService>('bannerService');

export interface IBannerService {
	readonly _serviceBrand: undefined;

	focus(): void;
	focusNextAction(): void;
	focusPreviousAction(): void;
	hide(id: string): void;
	show(item: IBannerItem): void;

	/**
	 * SAEngine: shows `element`, `height` pixels high, as a strip of its own above the banner's
	 * messages (the project stage bar) until the result is disposed. One strip at a time: a new
	 * one replaces the last.
	 */
	showStrip(element: HTMLElement, height: number): IDisposable;
}
