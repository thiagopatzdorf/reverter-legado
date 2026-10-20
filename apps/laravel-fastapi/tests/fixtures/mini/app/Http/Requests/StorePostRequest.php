<?php

namespace App\Http\Requests;

use Illuminate\Foundation\Http\FormRequest;

class StorePostRequest extends FormRequest
{
    public function rules()
    {
        return [
            'title' => 'required|string|max:20',
            'body' => 'required|string',
            'author_id' => 'required|integer|exists:authors,id',
        ];
    }
}
