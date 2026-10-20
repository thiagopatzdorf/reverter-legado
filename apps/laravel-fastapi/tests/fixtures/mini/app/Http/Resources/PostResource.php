<?php

namespace App\Http\Resources;

use Illuminate\Http\Resources\Json\JsonResource;

class PostResource extends JsonResource
{
    public static $wrap = 'post';

    public function toArray($request)
    {
        return [
            'id' => $this->resource->getKey(),
            'title' => $this->title,
            'author' => $this->resource->author->name,
            'createdAt' => $this->resource->created_at,
        ];
    }
}
