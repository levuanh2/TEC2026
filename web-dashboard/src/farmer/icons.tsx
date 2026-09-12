/* Farmer's icon vocabulary is the product's icon vocabulary — see ../icons.tsx.
 *
 * This file used to own the registry. It now re-exports the shared one so
 * Management renders the same mark for the same concept (a farm is a farm in
 * both work modes) without Farmer's imports having to change. */
export { Ico, type IconName } from '../icons'
