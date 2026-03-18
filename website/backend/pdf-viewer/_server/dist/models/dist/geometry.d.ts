/**
 * Clockwise direction
 * @public
 */
export declare enum Rotation {
    Degree0 = 0,
    Degree90 = 1,
    Degree180 = 2,
    Degree270 = 3
}
/** Clamp a Position to device-pixel integers (floor) */
export declare function toIntPos(p: Position): Position;
/** Clamp a Size so it never truncates right / bottom (ceil) */
export declare function toIntSize(s: Size): Size;
/** Apply both rules to a Rect */
export declare function toIntRect(r: Rect): Rect;
/**
 * Calculate degree that match the rotation type
 * @param rotation - type of rotation
 * @returns rotated degree
 *
 * @public
 */
export declare function calculateDegree(rotation: Rotation): 0 | 90 | 180 | 270;
/**
 * Calculate angle that match the rotation type
 * @param rotation - type of rotation
 * @returns rotated angle
 *
 * @public
 */
export declare function calculateAngle(rotation: Rotation): number;
/**
 * Represent the size of object
 *
 * @public
 */
export interface Size {
    /**
     * width of the object
     */
    width: number;
    /**
     * height of the object
     */
    height: number;
}
/**
 * Represents a rectangle defined by its left, top, right, and bottom edges
 *
 * @public
 */
export interface Box {
    /**
     * The x-coordinate of the left edge
     */
    left: number;
    /**
     * The y-coordinate of the top edge
     */
    top: number;
    /**
     * The x-coordinate of the right edge
     */
    right: number;
    /**
     * The y-coordinate of the bottom edge
     */
    bottom: number;
}
/**
 * Swap the width and height of the size object
 * @param size - the original size
 * @returns swapped size
 *
 * @public
 */
export declare function swap(size: Size): Size;
/**
 * Transform size with specified rotation angle and scale factor
 * @param size - orignal size of rect
 * @param rotation - rotation angle
 * @param scaleFactor - - scale factor
 * @returns size that has been transformed
 *
 * @public
 */
export declare function transformSize(size: Size, rotation: Rotation, scaleFactor: number): Size;
/**
 * position of point
 *
 * @public
 */
export interface Position {
    /**
     * x coordinate
     */
    x: number;
    /**
     * y coordinate
     */
    y: number;
}
/**
 * Quadrilateral
 *
 * @public
 */
export interface Quad {
    p1: Position;
    p2: Position;
    p3: Position;
    p4: Position;
}
/**
 * Convert quadrilateral to rectangle
 * @param q - quadrilateral
 * @returns rectangle
 *
 * @public
 */
export declare function quadToRect(q: Quad): Rect;
/**
 * Convert rectangle to quadrilateral
 * @param r - rectangle
 * @returns quadrilateral
 *
 * @public
 */
export declare function rectToQuad(r: Rect): Quad;
/**
 * Rotate the container and calculate the new position for a point
 * in specified position
 * @param containerSize - size of the container
 * @param position - position of the point
 * @param rotation - rotated angle
 * @returns new position of the point
 *
 * @public
 */
export declare function rotatePosition(containerSize: Size, position: Position, rotation: Rotation): Position;
/**
 * Calculate the position of point by scaling the container
 * @param position - position of the point
 * @param scaleFactor - factor of scaling
 * @returns new position of point
 *
 * @public
 */
export declare function scalePosition(position: Position, scaleFactor: number): Position;
/**
 * Calculate the position of the point by applying the specified transformation
 * @param containerSize - size of container
 * @param position - position of the point
 * @param rotation - rotated angle
 * @param scaleFactor - factor of scaling
 * @returns new position of point
 *
 * @public
 */
export declare function transformPosition(containerSize: Size, position: Position, rotation: Rotation, scaleFactor: number): Position;
/**
 * Restore the position in a transformed cotainer
 * @param containerSize - size of the container
 * @param position - position of the point
 * @param rotation - rotated angle
 * @param scaleFactor - factor of scaling
 * @returns the original position of the point
 *
 * @public
 */
export declare function restorePosition(containerSize: Size, position: Position, rotation: Rotation, scaleFactor: number): Position;
/**
 * representation of rectangle
 *
 * @public
 */
export interface Rect {
    /**
     * origin of the rectangle
     */
    origin: Position;
    /**
     * size of the rectangle
     */
    size: Size;
}
/**
 * Check if two rectangles are equal
 * @param a - first rectangle
 * @param b - second rectangle
 * @returns true if the rectangles are equal, false otherwise
 *
 * @public
 */
export declare function rectEquals(a: Rect, b: Rect): boolean;
/**
 * Calculate the rect from the given points
 * @param pts - points
 * @returns rect
 *
 * @public
 */
export declare function rectFromPoints(positions: Position[]): Rect;
/**
 * Transform the point by the given angle and translation
 * @param pos - point
 * @param angleRad - angle in radians
 * @param translate - translation
 * @returns transformed point
 *
 * @public
 */
export declare function rotateAndTranslatePoint(pos: Position, angleRad: number, translate: Position): Position;
/**
 * Expand the rect by the given padding
 * @param rect - rectangle
 * @param padding - padding
 * @returns expanded rect
 *
 * @public
 */
export declare function expandRect(rect: Rect, padding: number): Rect;
/**
 * Calculate the rect after rotated the container
 * @param containerSize - size of container
 * @param rect - target rect
 * @param rotation - rotation angle
 * @returns rotated rect
 *
 * @public
 */
export declare function rotateRect(containerSize: Size, rect: Rect, rotation: Rotation): Rect;
/**
 * Scale the rectangle
 * @param rect - rectangle
 * @param scaleFactor - factor of scaling
 * @returns new rectangle
 *
 * @public
 */
export declare function scaleRect(rect: Rect, scaleFactor: number): Rect;
/**
 * Calculate new rectangle after transforming the container
 * @param containerSize - size of the container
 * @param rect - the target rectangle
 * @param rotation - rotated angle
 * @param scaleFactor - factor of scaling
 * @returns new rectangle after transformation
 *
 * @public
 */
export declare function transformRect(containerSize: Size, rect: Rect, rotation: Rotation, scaleFactor: number): Rect;
/**
 * Calculate new rectangle before transforming the container
 * @param containerSize - size of the container
 * @param rect - the target rectangle
 * @param rotation - rotated angle
 * @param scaleFactor - factor of scaling
 * @returns original rectangle before transformation
 *
 * @public
 */
export declare function restoreRect(containerSize: Size, rect: Rect, rotation: Rotation, scaleFactor: number): Rect;
/**
 * Calculate the original offset in a transformed container
 * @param offset - position of the point
 * @param rotation - rotated angle
 * @param scaleFactor - factor of scaling
 * @returns original position of the point
 *
 * @public
 */
export declare function restoreOffset(offset: Position, rotation: Rotation, scaleFactor: number): Position;
/**
 * Return the smallest rectangle that encloses *all* `rects`.
 * If the array is empty, returns `null`.
 *
 * @param rects - array of rectangles
 * @returns smallest rectangle that encloses all the rectangles, or null if empty
 *
 * @public
 */
export declare function boundingRect(rects: Rect[]): Rect | null;
/**
 * Return the smallest rectangle that encloses *all* `rects`.
 * If the array is empty, returns an empty rect (origin at 0,0 with zero size).
 *
 * @param rects - array of rectangles
 * @returns smallest rectangle that encloses all the rectangles, or empty rect if empty
 *
 * @public
 */
export declare function boundingRectOrEmpty(rects: Rect[]): Rect;
export interface Matrix {
    a: number;
    b: number;
    c: number;
    d: number;
    e: number;
    f: number;
}
/**
 * Normalize an angle in degrees to the range [0, 360).
 *
 * @param degrees - angle in degrees
 * @returns normalized angle in [0, 360)
 *
 * @public
 */
export declare function normalizeAngle(degrees: number): number;
/**
 * Calculate the center of a rectangle.
 *
 * @param rect - rectangle
 * @returns center position
 *
 * @public
 */
export declare function getRectCenter(rect: Rect): Position;
/**
 * Rotate a point around a center by the given angle in degrees.
 *
 * @param point - the point to rotate
 * @param center - the center of rotation
 * @param angleDegrees - rotation angle in degrees
 * @returns rotated point
 *
 * @public
 */
export declare function rotatePointAround(point: Position, center: Position, angleDegrees: number): Position;
/**
 * Rotate an array of points around a center by the given angle in degrees.
 *
 * @param points - the points to rotate
 * @param center - the center of rotation
 * @param angleDegrees - rotation angle in degrees
 * @returns rotated points
 *
 * @public
 */
export declare function rotateVertices(points: Position[], center: Position, angleDegrees: number): Position[];
/**
 * Calculate the axis-aligned bounding box for a rectangle rotated around an arbitrary point.
 *
 * @param rect - the unrotated rectangle
 * @param angleDegrees - rotation angle in degrees
 * @param center - the center of rotation
 * @returns the AABB of the rotated rectangle
 *
 * @public
 */
export declare function calculateRotatedRectAABBAroundPoint(rect: Rect, angleDegrees: number, center: Position): Rect;
/**
 * Calculate the axis-aligned bounding box for a rectangle rotated around its own center.
 *
 * @param unrotatedRect - the unrotated rectangle
 * @param angleDegrees - rotation angle in degrees
 * @returns the AABB of the rotated rectangle
 *
 * @public
 */
export declare function calculateRotatedRectAABB(unrotatedRect: Rect, angleDegrees: number): Rect;
/**
 * Infer the world-space rotation center from unrotated rect + rotated AABB + angle.
 * Falls back to the unrotated rect center when angle is effectively 0.
 *
 * @param unrotatedRect - the unrotated rectangle
 * @param rotatedAabb - the axis-aligned bounding box of the rotated rectangle
 * @param angleDegrees - rotation angle in degrees
 * @returns the inferred rotation center
 *
 * @public
 */
export declare function inferRotationCenterFromRects(unrotatedRect: Rect, rotatedAabb: Rect, angleDegrees: number): Position;
export declare function buildUserToDeviceMatrix(rect: Rect, rotation: Rotation, outW: number, outH: number): Matrix;
